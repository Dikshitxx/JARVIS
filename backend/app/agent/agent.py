import json
import logging
import re
import threading
import time
from contextvars import copy_context
from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor

from app import tools  # noqa: F401 (register all tools)
from app.agent import runtime_context
from app.agent.guardrails import prepare_call, validate_call
from app.agent.prompts import build_system_prompt
from app.agent.request import UserRequest, build_user_request
from app.agent.router import is_fast_route_candidate, try_fast_route
from app.agent.utterance import UtteranceAnalysis, analyze_utterance
from app.core import config
from app.llm import client
from app.memory import store
from app.permissions.classify import classify
from app.tools.registry import REGISTRY, NeedsConfirmation, ToolResult, get_schemas, names_for_capabilities, run_tool_result


log = logging.getLogger("jarvis.agent")
MAX_TOOL_STEPS = 8
MAX_PARALLEL_TOOLS = 4
_FINAL_RESPONSE_TOOLS = {"get_time", "get_weather", "get_system_info", "calculate", "search_web", "fetch_web_page"}


def _normalize_pending_arguments(value, field: str = ""):
    if isinstance(value, dict):
        return {
            key: _normalize_pending_arguments(item, str(key).lower())
            for key, item in sorted(value.items())
        }
    if isinstance(value, list):
        return [_normalize_pending_arguments(item, field) for item in value]
    if isinstance(value, str):
        cleaned = value.strip()
        return cleaned if field in {"message", "text", "content"} else cleaned.casefold()
    return value


def _tool_observation(result: ToolResult) -> str:
    observation = {
        "status": result.status,
        "action": result.action,
        "target": result.target,
        "verification_status": result.verification_status,
        "error": result.error or None,
    }
    if result.data is not None:
        data = result.data
        if isinstance(data, dict) and isinstance(data.get("results"), list):
            data = {**data, "results": data["results"][:5]}
            data["results"] = [
                {**item, "snippet": str(item.get("snippet", ""))[:420]}
                for item in data["results"] if isinstance(item, dict)
            ]
        elif isinstance(data, dict) and isinstance(data.get("content"), str):
            data = {**data, "content": data["content"][:9_000]}
        observation["data"] = data
    else:
        observation["message"] = result.message[:10_000]
    encoded = json.dumps(observation, ensure_ascii=False, default=str)
    return encoded[:18_000]


def _planned_args(name: str, args: dict, action) -> dict:
    """Bind plan entities to tool parameters using their names and descriptions."""
    values = dict(args or {})
    tool = REGISTRY.get(name)
    properties = (tool.parameters.get("properties") or {}) if tool else {}
    target_fields = {"target", "url", "name", "application", "project", "contact", "target_window", "website"}
    query_fields = {"query", "search_query", "search_term", "message", "text", "content", "expression"}
    for field, definition in properties.items():
        lowered = field.lower()
        description = str(definition.get("description", "")).lower()
        if action.target and (lowered in target_fields or "target window" in description):
            values[field] = action.target
        elif action.query and (lowered in query_fields or "search query" in description):
            values[field] = action.query
        elif lowered == "browser":
            browser = next((item.split("=", 1)[1] for item in action.modifiers if item.startswith("browser=")), "")
            if browser:
                values[field] = browser
        elif lowered == "avoid_current":
            values[field] = "avoid_current" in action.modifiers
        elif lowered == "result_index":
            index = next((item.split("=", 1)[1] for item in action.modifiers if item.startswith("result_index=")), "")
            if index:
                values[field] = max(0, int(index))
        elif lowered in {"action", "operation", "mode"} and definition.get("enum"):
            intent_words = set(re.findall(r"[a-z]+", action.intent.lower()))
            matching = [choice for choice in definition["enum"] if str(choice).lower() in intent_words]
            if matching:
                values[field] = matching[0]
    return values


def _deterministic_plan_call(action) -> tuple[str, dict] | None:
    """Bind simple parsed desktop steps directly to their registered tools."""
    browser = next((item.split("=", 1)[1] for item in action.modifiers if item.startswith("browser=")), "")
    workflow = next((item.split("=", 1)[1] for item in action.modifiers if item.startswith("workflow=")), "")
    if workflow == "notepad_type_clear" and action.intent == "open_application" and action.target:
        return "open_app", {"name": action.target}
    if workflow == "notepad_type_clear" and action.intent == "type_text" and action.target and action.query:
        return "type_text", {"text": action.query, "target_window": action.target}
    if workflow == "notepad_type_clear" and action.intent == "clear_text" and action.target:
        return "clear_text", {"target_window": action.target}
    if action.intent == "pause_current_media":
        return "control_media", {"action": "pause"}
    if action.intent == "resume_current_media":
        return "control_media", {"action": "resume"}
    if action.intent == "play_media_content" and browser != "edge":
        return "play_youtube_song", {"query": action.query or "music", "avoid_current": "avoid_current" in action.modifiers}
    return None


def _strip_stray_tool_json(text: str) -> str:
    """Remove a stray raw tool-call object if the model emitted one as prose."""
    start = text.find('{"name"')
    if start == -1:
        return text
    depth = 0
    end = None
    for index in range(start, len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                end = index + 1
                break
    if end is None:
        return text
    cleaned = (text[:start] + text[end:]).strip()
    return cleaned or "I couldn't identify a valid action for that request."


def _confirmation_message(tool_name: str, args: dict) -> str:
    if tool_name == "send_whatsapp_message":
        return f"Send this to {args.get('contact')}?\n'{args.get('message')}'"
    return f"Should I {tool_name.replace('_', ' ')} with those details?"


def _mark_current_task(status: str, result: str, step: str) -> None:
    try:
        from app.tasks import current_task_id, update_task

        task_id = current_task_id()
        if task_id:
            update_task(task_id, status=status, result=result, current_step=step)
    except Exception:
        log.exception("Could not update the current task status")


class Agent:
    def __init__(self):
        try:
            self.history: list[dict] = store.recent_messages(config.MAX_HISTORY_MESSAGES)
        except Exception:
            log.exception("Could not load saved chat history")
            self.history = []
        saved_context = runtime_context.get_context()
        self.last_site: str | None = saved_context.get("last_site") or None
        self.last_search_query: str | None = saved_context.get("last_search_query") or None
        self.pending: tuple[str, dict, float] | None = None
        self.pending_task_id: str | None = None
        self.pending_continuation: dict | None = None
        self._lock = threading.RLock()
        persisted = runtime_context.get_context().get("pending_operation") or {}
        if persisted.get("status") == "confirmation_required":
            self.pending = (
                persisted.get("tool", ""),
                persisted.get("args", {}),
                float(persisted.get("created_at", time.time())),
            )
            self.pending_task_id = persisted.get("task_id")

    def _record_turn(self, user_text: str, reply: str, intent: str) -> None:
        with self._lock:
            self.history.extend((
                {"role": "user", "content": user_text},
                {"role": "assistant", "content": reply},
            ))
            self.history = self.history[-config.MAX_HISTORY_MESSAGES:]
        try:
            store.add_message("user", user_text)
            store.add_message("assistant", reply)
        except Exception:
            log.exception("Could not persist the chat turn")
        context = runtime_context.get_context()
        turns = list(context.get("recent_turns") or [])
        turns.append({
            "user": user_text.strip()[:1000], "assistant": reply.strip()[:1500],
            "intent": intent, "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        })
        runtime_context.update_context(recent_turns=turns[-8:])

    def _track_tool_state(self, name: str, args: dict, result) -> None:
        status = getattr(result, "status", "success")
        if name == "open_and_remember_site" and status == "success":
            self.last_site = str(args.get("site_name", "")).strip().lower() or self.last_site
        elif name in {"browser_open", "open_url"} and status == "success":
            from app.tools.browser import SITE_URLS

            target = str(args.get("target") or args.get("url") or "").strip().lower()
            if target in SITE_URLS:
                self.last_site = target
        if name == "search_web":
            self.last_search_query = str(args.get("query", "")).strip() or self.last_search_query

    def respond(self, user_text: str) -> str:
        context = runtime_context.get_context()
        pending = context.get("pending_operation") or {}
        with self._lock:
            if self.pending is None and pending.get("status") == "confirmation_required":
                self.pending = (
                    pending.get("tool", ""), pending.get("args", {}),
                    float(pending.get("created_at", time.time())),
                )
                self.pending_task_id = pending.get("task_id")
            pending_tuple = self.pending
            pending_task_id = self.pending_task_id
        if pending_tuple and pending.get("status") != "confirmation_required":
            runtime_context.update_context(pending_operation={
                "tool": pending_tuple[0], "args": pending_tuple[1], "status": "confirmation_required",
                "created_at": pending_tuple[2], "task_id": pending_task_id,
            })
            context = runtime_context.get_context()
        # Only honor a browser that the user or prior step has explicitly chosen.
        # Do not infer a browser from the active foreground app, because that
        # makes generic website opens like "open youtube" silently depend on a
        # specific browser instead of the managed browser default.
        with self._lock:
            has_pending = self.pending is not None or pending.get("status") == "confirmation_required"
        analysis = analyze_utterance(user_text, context, has_pending=has_pending)
        request = build_user_request(user_text, context, analysis)
        analysis = request.analysis or analysis
        context = runtime_context.begin_turn(user_text, analysis)
        try:
            from app.tasks import current_task_id, update_task

            task_id = current_task_id()
            if task_id:
                update_task(task_id, resolved_intent=request.intent, selected_capabilities=request.capabilities,
                            target=request.target, current_step=f"Routing {request.intent}")
        except Exception:
            pass
        if analysis.kind in {"action", "mixed", "follow_up"}:
            runtime_context.remember_user_entities(user_text)
        reply = self._respond(user_text, analysis, context, request)
        self._record_turn(user_text, reply, analysis.kind)
        with self._lock:
            has_pending = self.pending is not None
        if not has_pending and analysis.kind not in {"conversation", "information"}:
            runtime_context.finish_task(reply)
        return reply

    def _respond(self, user_text: str, analysis: UtteranceAnalysis, context: dict, request: UserRequest | None = None) -> str:
        request = request or build_user_request(user_text, context)
        with self._lock:
            pending = self.pending
        if analysis.confirmation and pending:
            return self._confirm_pending(user_text)
        if analysis.cancellation:
            with self._lock:
                had_pending = self.pending is not None
                pending_task_id = self.pending_task_id
                self.pending = None
                self.pending_task_id = None
                self.pending_continuation = None
            if had_pending:
                pending_info = context.get("pending_operation") or {}
                runtime_context.update_context(pending_operation={})
                origin_task_id = pending_info.get("task_id") or pending_task_id
                if origin_task_id:
                    from app.tasks import task_manager

                    task_manager.complete_confirmation(origin_task_id, "CANCELLED", "Cancelled. I won't run that action.")
                return "Cancelled. I won't run that action."
            last_action = context.get("last_action") or {}
            if last_action:
                return "That action has already completed. Tell me what you'd like undone and I'll check whether it can be reversed safely."
            return "There isn't a pending action to cancel. What would you like to do?"

        if is_fast_route_candidate(user_text):
            fast_result = try_fast_route(user_text, context, request)
            if fast_result is not None:
                tool_name, result, args = fast_result
                message = getattr(result, "message", str(result))
                if message.startswith("Confirm:"):
                    if not self._set_pending(tool_name, args):
                        return "Another action is still waiting for confirmation. Confirm or cancel it before starting another protected action."
                    return _confirmation_message(tool_name, args)
                else:
                    runtime_context.record_action(tool_name, args, result)
                    self._track_tool_state(tool_name, args, result)
                return message

        # The parser is supporting context only. Give the model the registered
        # safe tools for every non-trivial request so its decision is not bounded
        # by a regex-derived intent or capability guess.
        all_capabilities = frozenset(
            capability for tool in REGISTRY.values() for capability in tool.capabilities
        )
        request = replace(request, capabilities=all_capabilities, plan=(), ordered=False, objective=None)

        messages = [{
            "role": "system",
            "content": build_system_prompt(
                user_text,
                runtime_context.prompt_context(user_text, context, analysis),
                None,
            ),
        }]
        messages.append({"role": "user", "content": user_text})
        return self._run_tool_loop(user_text, messages, analysis, request)

    def _confirm_pending(self, user_text: str) -> str:
        with self._lock:
            pending = self.pending
            pending_task_id = self.pending_task_id
            continuation = self.pending_continuation
        if not pending:
            return "There isn't an action waiting for confirmation."
        name, args, created_at = pending
        pending_info = runtime_context.get_context().get("pending_operation") or {}
        origin_task_id = pending_info.get("task_id") or pending_task_id
        if time.time() - created_at > 300:
            with self._lock:
                self.pending = None
                self.pending_task_id = None
                self.pending_continuation = None
            runtime_context.update_context(pending_operation={})
            if origin_task_id:
                from app.tasks import task_manager

                task_manager.complete_confirmation(origin_task_id, "CANCELLED", "That confirmation expired.")
            return "That confirmation expired. Please ask again if you still want the action."

        with self._lock:
            self.pending = None
            self.pending_task_id = None
            self.pending_continuation = None
        runtime_context.update_context(pending_operation={})
        result = run_tool_result(name, args, confirmed=True)
        result_message = result.message
        self._track_tool_state(name, args, result)
        runtime_context.record_action(name, args, result)
        if origin_task_id:
            from app.tasks import task_manager

            completion = "FAILED" if result.status != "success" else "UNVERIFIED" if result.verification_status == "unknown" else "SUCCEEDED"
            task_manager.complete_confirmation(
                origin_task_id, completion, result_message, tool_name=name,
                arguments=args, verification=result.verification_status,
            )
        if continuation:
            messages = continuation["messages"]
            original_text = continuation["user_text"]
            if messages:
                messages[0] = {
                    "role": "system",
                    "content": build_system_prompt(original_text, runtime_context.prompt_context(original_text)),
                }
            messages.append({"role": "tool", "content": result_message, "tool_name": name})
            if result.status != "success":
                return result_message
            if continuation.get("plan_index") is not None:
                request = continuation["request"]
                next_plan_index = continuation["plan_index"] + 1
                if next_plan_index >= len(request.plan):
                    try:
                        final = client.chat(messages, tools=[])
                        text = getattr(final, "content", "") or ""
                        if text:
                            return _strip_stray_tool_json(text)
                    except Exception:
                        pass
                    return result_message
                return self._run_tool_loop(
                    original_text, messages, continuation["analysis"], request,
                    start_plan_index=next_plan_index, initial_results=[result_message],
                )
            return self._run_tool_loop(original_text, messages, continuation["analysis"], continuation["request"])
        return result_message

    def _set_pending(
        self, tool_name: str, args: dict, messages: list[dict] | None = None,
        user_text: str = "", analysis=None, request=None, plan_index: int | None = None,
    ) -> bool:
        created_at = time.time()
        from app.tasks import current_task_id, update_task

        task_id = current_task_id()
        with self._lock:
            if self.pending and time.time() - self.pending[2] <= 300:
                reply = "Another action is still waiting for confirmation. Confirm or cancel it before starting another protected action."
                _mark_current_task("BLOCKED", reply, "Waiting for an earlier confirmation")
                return False
            self.pending = (tool_name, args, created_at)
            self.pending_task_id = task_id
            self.pending_continuation = None
            if messages is not None:
                self.pending_continuation = {
                    "user_text": user_text, "messages": list(messages), "analysis": analysis,
                    "request": request, "plan_index": plan_index,
                }
        runtime_context.update_context(
            pending_operation={"tool": tool_name, "args": args, "status": "confirmation_required", "created_at": created_at, "task_id": task_id}
        )
        if task_id:
            update_task(task_id, status="WAITING_CONFIRMATION", current_step="Waiting for confirmation",
                        result=_confirmation_message(tool_name, args))
            from app.tools.registry import REGISTRY

            tool = REGISTRY.get(tool_name)
            from app.tasks import append_step

            append_step(task_id, tool_name=tool_name, capability=",".join(sorted(tool.capabilities)) if tool else "",
                        arguments=args, status="waiting_confirmation", result="Waiting for user confirmation.",
                        verification="unknown", side_effect=bool(tool and tool.side_effect))
        return True

    @staticmethod
    def _tool_calls(message) -> list[tuple[str, dict]]:
        calls = []
        for call in getattr(message, "tool_calls", None) or []:
            calls.append((call.function.name, dict(call.function.arguments or {})))
        if calls:
            return calls
        try:
            data = json.loads(getattr(message, "content", "") or "")
        except (json.JSONDecodeError, TypeError):
            return []
        if isinstance(data, dict) and data.get("name") in REGISTRY:
            return [(data["name"], data.get("parameters") or data.get("arguments") or {})]
        return []

    def _matches_pending_call(self, name: str, args: dict) -> bool:
        with self._lock:
            pending = self.pending
        if not pending or name != pending[0]:
            return False
        return _normalize_pending_arguments(args or {}) == _normalize_pending_arguments(pending[1] or {})

    def _prepare_tool(
        self,
        name: str,
        args: dict,
        user_text: str,
        request: UserRequest | None = None,
        plan_action=None,
    ):
        if plan_action is not None:
            args = _planned_args(name, args, plan_action)
        args = prepare_call(name, args)
        if name in {"type_text", "clear_text", "paste_text", "copy_selection", "copy_application_text", "copy_from_window"}:
            target_window = args.get("target_window", "")
            args["target_window"] = target_window
            if not target_window:
                return args, ToolResult("clarification_required", "Which open application window should receive or provide that text?"), False
        reason = validate_call(name, args, user_text)
        if reason:
            return args, ToolResult("invalid_action", reason), False
        decision, _reason = classify(name, args)
        if decision == "CONFIRM":
            raise NeedsConfirmation(name, args)
        result = run_tool_result(name, args)
        return args, result, True

    def _can_run_parallel(self, calls: list[tuple[str, dict]], user_text: str, request: UserRequest | None = None) -> bool:
        if request is not None and (request.ordered or request.plan):
            return False
        if len(calls) < 2 or len(calls) > MAX_PARALLEL_TOOLS:
            return False
        resources = []
        for name, raw_args in calls:
            tool = REGISTRY.get(name)
            if tool is None or not tool.parallel_safe:
                return False
            args = prepare_call(name, raw_args)
            if validate_call(name, args, user_text):
                return False
            decision, _ = classify(name, args)
            if decision != "ALLOW":
                return False
            if tool.resource:
                resources.append(tool.resource)
        return len(resources) == len(set(resources))

    def _execute_calls(
        self,
        calls: list[tuple[str, dict]],
        user_text: str,
        request: UserRequest | None = None,
        plan_action=None,
    ):
        if self._can_run_parallel(calls, user_text, request):
            def execute(call):
                name, raw_args = call
                args = prepare_call(name, raw_args)
                if name in {"type_text", "paste_text", "copy_selection", "copy_application_text", "copy_from_window"}:
                    args["target_window"] = args.get("target_window", "")
                try:
                    result = run_tool_result(name, args)
                except NeedsConfirmation as need:
                    return name, args, need
                return name, args, result

            with ThreadPoolExecutor(max_workers=min(len(calls), MAX_PARALLEL_TOOLS)) as pool:
                futures = [pool.submit(copy_context().run, execute, call) for call in calls]
                outcomes = [future.result() for future in futures]
            for name, args, result in outcomes:
                if isinstance(result, NeedsConfirmation):
                    return None, result
            return [(name, args, result) for name, args, result in outcomes], None

        name, raw_args = calls[0]
        try:
            args, result, _allowed = self._prepare_tool(name, raw_args, user_text, request, plan_action)
        except NeedsConfirmation as need:
            return None, need
        if result is None:
            result = run_tool_result(name, args)
        return [(name, args, result)], None

    def _run_tool_loop(
        self, user_text: str, messages: list[dict], analysis: UtteranceAnalysis,
        request: UserRequest, *, start_plan_index: int = 0,
        initial_results: list[str] | None = None,
    ) -> str:
        completed_results: list[str] = list(initial_results or [])
        has_web_evidence = False
        allowed_names = {name for name, tool in REGISTRY.items() if tool.risk != "blocked"}
        plan_index = start_plan_index
        for _ in range(MAX_TOOL_STEPS):
            plan_action = request.plan[plan_index] if plan_index < len(request.plan) else None
            from app.tasks import cancellation_requested

            if cancellation_requested():
                return "I stopped after the current operation finished."
            if plan_action is not None and plan_action.intent == "play_media_content":
                requested_browser = next(
                    (item.split("=", 1)[1] for item in plan_action.modifiers if item.startswith("browser=")),
                    "",
                )
                if requested_browser == "edge":
                    completed = "; ".join(completed_results)
                    prefix = f"{completed} " if completed else ""
                    reply = (
                        f"{prefix}I couldn't start playback specifically in Edge. JARVIS runs its controlled YouTube player in the configured Brave session, "
                        "and system media keys cannot target a named browser's media session."
                    )
                    _mark_current_task("FAILED", reply, "Edge-targeted playback is unavailable")
                    return reply
            if plan_action is not None:
                relevant = names_for_capabilities({plan_action.capability}) & allowed_names
            else:
                relevant = None
            schemas = get_schemas(relevant)
            deterministic_call = _deterministic_plan_call(plan_action) if plan_action is not None else None
            if deterministic_call is not None:
                message = None
                calls = [deterministic_call]
            else:
                try:
                    message = client.chat(messages, tools=schemas)
                except Exception as exc:
                    log.warning("Local model request failed: %s", exc)
                    if completed_results:
                        reply = "I completed the available actions, but couldn't finish the rest of that request."
                        _mark_current_task("FAILED", reply, "Could not finish planned steps")
                        return reply
                    reply = "I couldn't reach the local language model. Please try again."
                    _mark_current_task("BLOCKED", reply, "Local model unavailable")
                    return reply

                calls = self._tool_calls(message)
                if calls:
                    log.info("LLM_TOOL_DECISION tools=%s", [name for name, _args in calls])
                    for name, args in calls:
                        log.info("TOOL_CALL name=%s argument_keys=%s", name, sorted(args))
                    if self._matches_pending_call(*calls[0]):
                        log.info("PENDING_CONFIRMATION_INTERPRETED tool=%s", calls[0][0])
                        return self._confirm_pending(user_text)
            if not calls:
                if plan_index and plan_index < len(request.plan):
                    reply = "I completed part of the request, but couldn't complete its remaining planned steps."
                    _mark_current_task("FAILED", reply, "Could not finish planned steps")
                    return reply
                reply = _strip_stray_tool_json(getattr(message, "content", "") or "") or "I couldn't form a response. Please try again."
                if completed_results:
                    _mark_current_task("SUCCEEDED", reply, "The requested tool action completed")
                    return reply
                if analysis.kind in {"action", "follow_up", "mixed", "information"}:
                    _mark_current_task("BLOCKED", reply, "No action was executed")
                return reply

            plan_names = names_for_capabilities({plan_action.capability}) & allowed_names if plan_action is not None else None
            unauthorized = [
                name for name, _args in calls
                if name not in allowed_names or (plan_names is not None and name not in plan_names)
            ]
            if unauthorized:
                log.warning("Model returned tools outside request capabilities: %s", unauthorized)
                if plan_action is not None:
                    reply = "I couldn't safely carry out the next planned step. Please clarify the request."
                else:
                    reply = "I couldn't match that action to an available capability. Please clarify what you want me to do."
                _mark_current_task("BLOCKED", reply, "Capability or target needs clarification")
                return reply

            model_returned_multiple = len(calls) > 1
            executable_calls = calls if self._can_run_parallel(calls, user_text, request) else calls[:1]
            if plan_action is not None:
                executable_calls = [
                    (name, _planned_args(name, args, plan_action)) for name, args in executable_calls
                ]
            if message is not None:
                assistant_message = {"role": "assistant", "content": getattr(message, "content", "") or ""}
                if getattr(message, "tool_calls", None):
                    assistant_message["tool_calls"] = [
                        {"function": {"name": name, "arguments": args}}
                        for name, args in executable_calls
                    ]
                messages.append(assistant_message)

            outcomes, confirmation = self._execute_calls(executable_calls, user_text, request, plan_action)
            if confirmation is not None:
                if not self._set_pending(
                    confirmation.tool_name, confirmation.tool_args, messages,
                    user_text, analysis, request,
                    plan_index=plan_index if plan_action is not None else None,
                ):
                    return "Another action is still waiting for confirmation. Confirm or cancel it before starting another protected action."
                return _confirmation_message(confirmation.tool_name, confirmation.tool_args)
            if not outcomes:
                return "I couldn't complete that request."

            for name, args, result in outcomes:
                log.info("TOOL_RESULT name=%s status=%s verification=%s", name, result.status, result.verification_status)
                runtime_context.record_action(name, args, result)
                self._track_tool_state(name, args, result)
                observation = _tool_observation(result)
                messages.append({"role": "tool", "content": observation, "tool_name": name})
                log.info("TOOL_OBSERVATION name=%s bytes=%s", name, len(observation))
                if result.status == "success":
                    completed_results.append(result.message)
                    if name == "search_web":
                        has_web_evidence = True

            failures = [result for _name, _args, result in outcomes if result.status != "success"]
            if failures:
                if any(name == "search_web" for name, _args, _result in outcomes) and not has_web_evidence:
                    reply = failures[0].message
                    _mark_current_task("FAILED", reply, "Web search did not retrieve evidence")
                    return reply
                if any(name == "look_at_screen" for name, _args, _result in outcomes):
                    reply = failures[0].message
                    _mark_current_task("FAILED", reply, "Vision inspection failed")
                    return reply
                if any(name == "play_youtube_song" for name, _args, _result in outcomes):
                    reply = failures[0].message
                    _mark_current_task("FAILED", reply, "YouTube playback failed")
                    return reply
                if has_web_evidence and all(name == "fetch_web_page" for name, _args, result in outcomes if result.status != "success"):
                    log.info("AGENT_NEXT_STEP reason=page_fetch_failed_using_existing_search_evidence")
                    continue
                _mark_current_task("FAILED", failures[0].message, "Tool operation failed")
                return failures[0].message

            if {name for name, _args, _result in outcomes} == {"look_at_screen"}:
                # Vision already returns its grounded answer; an additional
                # LLM paraphrase could replace it with unsupported details.
                reply = outcomes[0][2].message
                _mark_current_task("SUCCEEDED", reply, "Vision inspection completed")
                return reply

            if cancellation_requested():
                return "I stopped after the current operation finished."

            if plan_action is not None:
                plan_index += len(outcomes)
                if plan_index == len(request.plan):
                    if all(_deterministic_plan_call(action) is not None for action in request.plan):
                        return "; ".join(completed_results) or "I completed the planned steps."
                    try:
                        final = client.chat(messages, tools=[])
                        text = getattr(final, "content", "") or ""
                        if text:
                            return _strip_stray_tool_json(text)
                    except Exception:
                        pass
                    return "; ".join(completed_results) or "I completed the planned steps."
                continue

            executed_names = {name for name, _args, _result in outcomes}
            has_information_result = bool(executed_names & _FINAL_RESPONSE_TOOLS)
            must_compose = analysis.kind == "mixed" or model_returned_multiple or has_information_result
            if must_compose:
                log.info("AGENT_NEXT_STEP reason=tool_observation tools=%s", sorted(executed_names))
                # Re-plan after a dependent first step. Independent batches are
                # already complete, so ask once for the user-facing synthesis.
                if model_returned_multiple and len(outcomes) == len(calls):
                    try:
                        final = client.chat(messages, tools=[])
                        text = getattr(final, "content", "") or ""
                        if text:
                            return _strip_stray_tool_json(text)
                    except Exception as exc:
                        log.warning("Final response generation failed: %s", exc)
                        if completed_results:
                            return "; ".join(completed_results)
                continue

            return "\n".join(result.message for _name, _args, result in outcomes)

        if completed_results:
            return "I completed these steps: " + "; ".join(completed_results[-6:]) + "."
        reply = "I couldn't complete that request. Please try phrasing it another way."
        _mark_current_task("FAILED", reply, "Tool step limit reached")
        return reply

    def reset(self):
        with self._lock:
            self.history.clear()
            self.pending = None
            self.pending_task_id = None
            self.pending_continuation = None
            self.last_site = None
            self.last_search_query = None
            store.clear_messages()
            runtime_context.store.clear_runtime_context()


agent = Agent()
