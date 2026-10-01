"""Persistent, bounded short-term context for the active conversation."""

import re
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime

from app.agent.utterance import UtteranceAnalysis
from app.memory import store
from app.tools.browser_targets import browser_search_url, resolve_target


_SEARCH_RE = re.compile(r"^(?:now\s+)?(?:search|find|look up)\s+(?:for\s+)?(.+?)\s*[.!?]*$", re.I)
_REFERENCE_RE = re.compile(r"\b(?:it|that|this|another|again|also|then|instead|actually|previous|first|second|continue|same|more)\b", re.I)
_request_context: ContextVar[dict | None] = ContextVar("jarvis_request_context", default=None)


def get_context() -> dict:
    """Return the current request's isolated context, or the saved conversation state."""
    local = _request_context.get()
    return dict(local) if local is not None else store.get_runtime_context()


def update_context(**updates) -> dict:
    """Update request-local state during a task; update SQLite for direct calls."""
    local = _request_context.get()
    if local is None:
        return store.update_runtime_context(**updates)
    local.update({key: value for key, value in updates.items() if key in store._RUNTIME_DEFAULTS})
    return dict(local)


def activate_request(task_id: str) -> dict:
    """Mark a submitted request as the newest conversation turn and snapshot state."""
    store.update_runtime_context(active_request_id=task_id)
    return store.get_runtime_context()


@contextmanager
def request_context_scope(task_id: str, initial: dict):
    """Isolate a task's context and commit it only if no newer request took over."""
    local = {**store._RUNTIME_DEFAULTS, **initial}
    token = _request_context.set(local)
    try:
        yield local
    finally:
        _request_context.reset(token)
        store.commit_runtime_context_if_active(task_id, local)


def _trim(value, limit: int = 500) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        value = str(value)
    return value.strip()[:limit]


def begin_turn(user_text: str, analysis: UtteranceAnalysis | None = None) -> dict:
    """Start a task only for a new action; follow-ups extend its task context."""
    from app.agent.utterance import analyze_utterance

    context = get_context()
    analysis = analysis or analyze_utterance(user_text, context)
    is_new_task = analysis.kind in {"action", "mixed", "information"} and not analysis.refers_to_context
    updates = {"previous_intent": analysis.kind}
    if is_new_task:
        updates.update(
            current_task=_trim(user_text, 500),
            current_task_id=uuid.uuid4().hex,
            current_task_step="understanding",
            task_actions=[],
            task_episode_saved=False,
        )
        if (context.get("pending_operation") or {}).get("status") != "confirmation_required":
            updates["pending_operation"] = {"request": _trim(user_text, 500), "status": "understanding"}
    update_context(**updates)
    context.update(updates)
    return context


def contextual_browser_intent(user_text: str, context: dict | None = None) -> dict | None:
    """Resolve an unqualified follow-up search from the active site/app."""
    context = context or get_context()
    match = _SEARCH_RE.match(user_text.strip())
    if not match:
        return None
    query = re.sub(r"\s+in\s+(?:the\s+)?browser$", "", match.group(1).strip(), flags=re.I).rstrip(".!?")
    if query.lower() in {"that", "it", "this", "that one", "it in the browser", "that in the browser"}:
        query = (
            context.get("clipboard_context")
            or context.get("last_query")
            or context.get("current_media")
            or (context.get("recent_entities") or [""])[-1]
        )
    if not query:
        return None
    current_browser = str(context.get("current_browser") or "").lower()
    if current_browser in {"brave", "chrome", "edge"}:
        return {"intent": "search_in_application", "name": current_browser, "query": query}
    target_name = context.get("current_target") or context.get("browser_target") or ""
    target = resolve_target(target_name) if target_name else None
    if target is None or "search" not in target.capabilities:
        return None
    return {"intent": "browser_search", "target": target.name, "query": query, "operation": "search"}


def contextual_media_intent(user_text: str, context: dict | None = None) -> dict | None:
    """Support unambiguous media controls; broader follow-ups go to the LLM."""
    context = context or get_context()
    if not context.get("active_media"):
        return None
    match = re.fullmatch(r"\s*(pause|resume|play|stop)(?:\s+(?:it|that|the\s+(?:video|song|music)))?[.!?]*\s*", user_text, re.I)
    if not match:
        return None
    action = match.group(1).lower()
    return {"intent": "control_media", "action": "pause" if action == "stop" else action}


def remember_user_entities(user_text: str) -> None:
    """Keep small, recent textual references in short-term state only."""
    context = get_context()
    entities = list(context.get("recent_entities") or [])
    search = _SEARCH_RE.match(user_text.strip())
    if search:
        query = search.group(1).strip().rstrip(".!?")
        if query and not _REFERENCE_RE.search(query):
            entities.append(query[:160])
            update_context(last_query=query[:300])
    quoted = re.findall(r"[\"']([^\"']{2,160})[\"']", user_text)
    entities.extend(quoted)
    entities = list(dict.fromkeys(item.strip() for item in entities if item.strip()))[-10:]
    update_context(recent_entities=entities)


def _json_safe(value, depth: int = 0):
    if depth > 4:
        return _trim(value, 120)
    if value is None or isinstance(value, (str, int, float, bool)):
        return _trim(value, 240) if isinstance(value, str) else value
    if isinstance(value, dict):
        return {str(key)[:60]: _json_safe(item, depth + 1) for key, item in list(value.items())[:20]}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item, depth + 1) for item in value[:20]]
    return _trim(value, 120)


def record_action(tool_name: str, args: dict, result) -> dict:
    """Persist action outcomes and update useful state on success or failure."""
    status = getattr(result, "status", "success")
    message = getattr(result, "message", str(result))
    if not hasattr(result, "status"):
        lowered = message.lower()
        if lowered.startswith(("error:", "failed:", "refused:", "could not", "i couldn't", "not found", "unsupported")):
            status = "failure"
    data = getattr(result, "data", None)
    context = get_context()
    safe_args = _json_safe(args or {})
    action = {
        "tool": tool_name,
        "args": safe_args,
        "status": status,
        "verification_status": getattr(result, "verification_status", "unknown"),
        "result": _trim(message, 500),
        "at": datetime.now().isoformat(timespec="seconds"),
    }
    actions = list(context.get("task_actions") or [])
    actions.append({"tool": tool_name, "result": _trim(message, 240), "status": status})
    updates = {
        "last_action": action,
        "last_tool_result": _trim(message, 500),
        "current_task_step": f"{tool_name}: {status}",
        "task_actions": actions[-12:],
        "pending_operation": (
            context.get("pending_operation")
            if (context.get("pending_operation") or {}).get("status") == "confirmation_required"
            else {"tool": tool_name, "args": safe_args, "status": status}
        ),
    }

    target_name = safe_args.get("target") or safe_args.get("url") or safe_args.get("site_name") or ""
    target = resolve_target(str(target_name)) if target_name else None
    if target:
        updates["current_target"] = target.name
        updates["browser_target"] = target.name
        updates["active_service"] = target.name
    if safe_args.get("query"):
        query = _trim(safe_args["query"], 300)
        updates["last_query"] = query
        if tool_name == "search_web":
            updates["last_search_query"] = query
        updates["recent_entities"] = list(dict.fromkeys(context.get("recent_entities", []) + [query[:160]]))[-10:]

    # Preserve target and media context when the operation fails. Store the
    # failure beside that context so a later correction can still refer to it.
    if status != "success":
        updates["failed_operation"] = action
    else:
        updates["failed_operation"] = {}
        if tool_name in {"open_app", "focus_app"}:
            app_name = str(safe_args.get("name", ""))
            if app_name:
                updates["current_application"] = app_name
                try:
                    from app.tools.apps import resolve_application_name

                    browser_app = resolve_application_name(app_name)
                    if browser_app in {"brave", "chrome", "edge"}:
                        updates["current_browser"] = browser_app
                        updates["current_target"] = ""
                        updates["browser_target"] = ""
                        updates["page_url"] = ""
                except Exception:
                    pass
        if tool_name == "close_app":
            closed_name = str(safe_args.get("name", ""))
            try:
                from app.tools.apps import resolve_application_name, resolve_application_reference

                closed_app = resolve_application_reference(closed_name) or closed_name.strip().lower()
                current_app = resolve_application_name(str(context.get("current_application") or ""))
                current_browser = resolve_application_name(str(context.get("current_browser") or ""))
            except Exception:
                closed_app = closed_name.strip().lower()
                current_app = str(context.get("current_application") or "").strip().lower()
                current_browser = str(context.get("current_browser") or "").strip().lower()
            if current_app == closed_app:
                updates["current_application"] = ""
                updates["current_window"] = ""
            if closed_app in {"brave", "chrome", "edge"} and current_browser in {"", closed_app}:
                updates.update(
                    current_browser="", current_target="", browser_target="", page_url="",
                    active_pages=[], environment_state={}, environment_observed_at="",
                )
                if current_browser == closed_app or closed_app == "brave":
                    updates.update(active_media="", current_media="", media_state="stopped")
        if tool_name in {"browser_open", "browser_search", "browser_interaction", "open_url", "open_and_remember_site", "search_web", "play_youtube_song"}:
            if target:
                selected_browser = str(safe_args.get("browser") or "Brave")
                updates["current_browser"] = selected_browser
            if target and target.search_url and safe_args.get("query"):
                updates["page_url"] = browser_search_url(target, str(safe_args["query"])) or target.canonical_url
            elif target and tool_name in {"browser_open", "open_url", "open_and_remember_site"}:
                updates["page_url"] = target.canonical_url
            if tool_name in {"open_and_remember_site", "browser_open", "open_url"} and target:
                updates["last_site"] = target.name
            if tool_name == "search_web":
                updates["last_search_query"] = str(safe_args.get("query", ""))
            if tool_name == "play_youtube_song" and not safe_args.get("browser"):
                try:
                    from app.tools.browser_session import get_browser_session

                    pages = get_browser_session().snapshot()
                    if pages:
                        updates["active_pages"] = pages[-6:]
                        current_page = pages[-1]
                        updates["page_url"] = current_page["url"]
                        updates["current_target"] = current_page["key"]
                except Exception:
                    pass
        if tool_name == "search_in_application":
            updates["current_browser"] = str(safe_args.get("name", "")).lower()
            updates["current_application"] = updates["current_browser"]
            updates["current_target"] = ""
            updates["browser_target"] = ""
        if tool_name == "play_youtube_song":
            updates["active_media"] = "youtube"
            updates["active_service"] = "youtube"
            media_data = data if isinstance(data, dict) else {}
            updates["current_media"] = _trim(media_data.get("media_title") or safe_args.get("query", ""), 300)
            updates["media_state"] = "playing"
        if tool_name in {"control_media", "media_control"}:
            updates["media_state"] = str(safe_args.get("action", "unknown"))
        if tool_name == "inspect_current_media" and status == "success" and isinstance(data, dict):
            updates["active_media"] = "youtube"
            updates["active_service"] = "youtube"
            updates["current_media"] = _trim(data.get("media_title", ""), 300)
            updates["media_state"] = _trim(data.get("media_state", "unknown"), 30)
        if tool_name == "type_text" and safe_args.get("text"):
            updates["last_text"] = _trim(safe_args["text"], 500)
        if isinstance(data, dict) and data.get("clipboard") is not None:
            updates["clipboard_context"] = _trim(data["clipboard"], 1000)
        if tool_name in {"open_app", "focus_app", "type_text", "press_key", "copy_text", "copy_selection", "copy_from_window", "paste_text"}:
            try:
                from app.tools.apps import get_active_window_info

                active = get_active_window_info()
                if active.get("title"):
                    updates["current_window"] = _trim(active["title"], 200)
                if active.get("application"):
                    process_name = str(active["application"])
                    try:
                        from app.tools.apps import resolve_application_name

                        normalized = resolve_application_name(process_name.removesuffix(".exe"))
                    except Exception:
                        normalized = None
                    updates["current_application"] = normalized or _trim(process_name, 100)
            except Exception:
                pass
        if tool_name in {"inspect_environment", "observe_environment", "get_environment_snapshot"} and isinstance(data, dict):
            updates["environment_state"] = {
                "observed_at": data.get("observed_at"),
                "active_window": data.get("active_window"),
                "browser": data.get("browser"),
            }
            updates["environment_observed_at"] = data.get("observed_at")
    return update_context(**updates)


def prompt_context(user_text: str, context: dict | None = None, analysis: UtteranceAnalysis | None = None) -> dict:
    """Expose bounded context in distinct categories for LLM interpretation."""
    context = context or get_context()
    recent = (context.get("recent_turns") or [])[-5:]
    conversation_turns = [
        {"user": str(turn.get("user", ""))[:400], "assistant": str(turn.get("assistant", ""))[:600]}
        for turn in recent if turn.get("intent") in {"conversation", "information"}
    ][-3:]
    action_turns = [
        {"user": str(turn.get("user", ""))[:400], "assistant": str(turn.get("assistant", ""))[:600]}
        for turn in recent if turn.get("intent") in {"action", "follow_up", "mixed"}
    ][-2:]
    task_values = {
        key: context.get(key) for key in ("current_task", "current_task_step", "pending_operation")
    }
    if task_values.get("current_task_step") == "completed":
        task_values.pop("current_task", None)
        task_values.pop("current_task_step", None)
    categories = {
        "conversation_context": {"recent_turns": conversation_turns},
        "action_context": {
            "recent_action_turns": action_turns,
            **{key: context.get(key) for key in ("last_action", "last_tool_result", "failed_operation")},
        },
        "search_context": {
            key: context.get(key) for key in ("last_query", "last_search_query", "last_site")
        },
        "browser_context": {
            key: context.get(key) for key in ("current_application", "current_window", "current_browser", "current_target", "browser_target", "page_url")
        },
        "task_context": task_values,
    }
    return {
        category: {key: value for key, value in items.items() if value not in (None, "", [], {})}
        for category, items in categories.items()
        if any(value not in (None, "", [], {}) for value in items.values())
    }

def finish_task(reply: str) -> None:
    context = get_context()
    goal = str(context.get("current_task") or "").strip()
    actions = context.get("task_actions") or []
    if (
        goal and not context.get("task_episode_saved") and len(actions) >= 2
        and all(item.get("status") == "success" for item in actions)
    ):
        summary = "; ".join(item.get("result", "") for item in actions[-8:]) or reply
        store.add_task_episode(goal, summary)
        update_context(task_episode_saved=True, pending_operation={})
    else:
        update_context(current_task_step="completed", pending_operation={})
