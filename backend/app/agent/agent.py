import json
import logging
import time
import re
from concurrent.futures import ThreadPoolExecutor

from app import tools  # noqa: F401  (loads and registers tools)
from app.agent.guardrails import check_ambiguous_request, check_known_gap, prepare_call, validate_call
from app.agent.prompts import build_system_prompt
from app.agent.router import try_fast_route
from app.core import config
from app.llm import client
from app.tools.registry import REGISTRY, NeedsConfirmation, ToolResult, get_schemas, run_tool, run_tool_result
from app.tools.browser_targets import parse_browser_intent

def _strip_stray_tool_json(text: str) -> str:
    """Removes any raw {"name": ...} tool-call-shaped JSON the model
    accidentally mixed into its natural-language reply as plain text.
    Uses brace counting instead of a naive regex, so it correctly handles
    nested JSON like {"name": "x", "parameters": {"y": "z"}}."""
    start = text.find('{"name"')
    if start == -1:
        return text
    depth = 0
    end = None
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    if end is None:
        return text
    cleaned = (text[:start] + text[end:]).strip()
    return cleaned or "I couldn't identify a valid action for that request."


log = logging.getLogger("jarvis.agent")

MAX_TOOL_STEPS = 4
DIRECT_REPLY_TOOLS = {"remember_fact", "forget_memory", "list_memories", "open_app", "close_app", "take_screenshot", "remember_person", "list_known_people", "move_mouse", "click_mouse", "type_text", "press_key", "start_project", "stop_project", "project_status", "open_url", "search_web", "play_youtube_song", "copy_text", "paste_text", "send_whatsapp_message"}
YES = {"yes", "y", "yeah", "yep", "confirm", "confirmed", "do it", "go ahead"}
NO = {"no", "n", "nope", "cancel", "stop", "dont", "don't"}
def _select_relevant_tools(user_text: str) -> set[str] | None:
    text = user_text.lower().strip()
    browser_intent = parse_browser_intent(user_text)
    if browser_intent is not None:
        return {browser_intent["intent"]}
    if re.search(r"\b(weather|temperature|forecast)\b", text):
        return {"get_weather"}
    if re.search(r"\b(time|date|today's date)\b", text):
        return {"get_time"}
    if re.search(r"\b(ram|cpu|disk|system resources|performance)\b", text):
        return {"get_system_info"}
    if re.search(r"\b(what can you do|what are you capable of|how are you|hello|hi|thanks)\b", text):
        return set()
    if re.search(r"\b(calculate|compute|what is)\b.*[0-9+*/%()-]", text):
        return {"calculate"}
    if re.search(r"\b(run|execute)\b.*\b(command|git|ollama|version)", text):
        return {"run_command"}
    if re.search(r"\b(file|files|folder|folders)\b", text):
        return {"list_files", "read_text_file"}
    if re.search(r"\b(search|find|look up)\b", text):
        return {"open_url", "search_web"}
    if re.search(r"\b(whatsapp|message|greet|send)\b", text):
        return {"send_whatsapp_message", "remember_person"}
    if re.search(r"\b(open|launch|close)\b", text):
        return {"open_app", "close_app"}
    return set()


def _confirmation_message(tool_name: str, args: dict) -> str:
    if tool_name == "send_whatsapp_message":
        return f"Send this to {args.get('contact')}?\n'{args.get('message')}'"
    return f"Confirm: {tool_name} {args}? Reply 'yes' or 'no'."


class Agent:
    def __init__(self):
        self.history: list[dict] = []
        self.pending: tuple[str, dict, float] | None = None  # action waiting for the user's yes/no

    def _remember_turn(self, user_text: str, reply: str) -> None:
        self.history.append({"role": "user", "content": user_text})
        self.history.append({"role": "assistant", "content": reply})
        self.history = self.history[-config.MAX_HISTORY_MESSAGES:]

    def _handle_pending(self, user_text: str) -> str | None:
        answer = user_text.strip().lower().strip(" .!")
        name, args, created_at = self.pending
        self.pending = None  # any message resolves or drops the pending action
        if time.time() - created_at > 300:
            return "That confirmation request expired. Please ask again."
        if answer in YES:
            log.info("CONFIRMED %s %s", name, args)
            return run_tool(name, args, confirmed=True)
        if answer in NO:
            return "Cancelled. Nothing was done."
        return None  # not an answer: the pending action is dropped, continue normally

    def respond(self, user_text: str) -> str:
        bare = user_text.strip().lower().strip(" .!")
        if not self.pending and (bare in YES or bare in NO):
            reply = "There is nothing waiting for your confirmation."
            self._remember_turn(user_text, reply)
            return reply

        if self.pending:
            outcome = self._handle_pending(user_text)
            if outcome is not None:
                self._remember_turn(user_text, outcome)
                return outcome

        # Try the fast deterministic router FIRST — no LLM call at all if it matches.
        ambiguous_message = check_ambiguous_request(user_text)
        if ambiguous_message is not None:
            self._remember_turn(user_text, ambiguous_message)
            return ambiguous_message

        fast_result = try_fast_route(user_text)
        if fast_result is not None:
            tool_name, result, args = fast_result
            if result.startswith("Confirm:"):
                # extract back out what router.py already built as (tool, args) via NeedsConfirmation
                self.pending = (tool_name, args, time.time())
            self._remember_turn(user_text, result)
            return result

        gap_message = check_known_gap(user_text)
        if gap_message is not None:
            self._remember_turn(user_text, gap_message)
            return gap_message

        self.history.append({"role": "user", "content": user_text})
        self.history = self.history[-config.MAX_HISTORY_MESSAGES:]

        messages = [{"role": "system", "content": build_system_prompt(user_text)}] + self.history
        reply = "I couldn't complete that request."
        finished = False

        for _ in range(MAX_TOOL_STEPS):
            msg = None
            for attempt in range(2):
                try:
                    relevant = _select_relevant_tools(user_text)
                    log.info("RELEVANT TOOLS: %s", relevant if relevant else "ALL (no confident match)")
                    msg = client.chat(messages, tools=get_schemas(relevant, include_core=relevant is None))
                    break
                except Exception as e:
                    log.warning("model error (attempt %s): %s", attempt + 1, e)
            if msg is None:
                reply = "Sorry boss, I could not process that. Try rephrasing, or give me one fact at a time."
                break
            log.info("tool_calls=%s content=%r", msg.tool_calls, msg.content)

            calls = []
            if msg.tool_calls:
                calls = [(c.function.name, dict(c.function.arguments or {})) for c in msg.tool_calls]
            else:
                try:
                    data = json.loads(msg.content or "")
                    if isinstance(data, dict) and data.get("name") in REGISTRY:
                        calls = [(data["name"], data.get("parameters") or data.get("arguments") or {})]
                except (json.JSONDecodeError, TypeError):
                    pass

            if not calls:
                reply = _strip_stray_tool_json(msg.content or "")
                break

            messages.append({"role": "assistant", "content": msg.content or ""})
            results = []

            def _run_one(name, args):
                args = prepare_call(name, args)
                skip_reason = validate_call(name, args, user_text)
                if skip_reason:
                    log.info("GUARDRAIL BLOCKED %s: %r (user said: %r)", name, skip_reason, user_text)
                    return name, ToolResult("invalid_action", skip_reason), None
                try:
                    r = run_tool_result(name, args)
                    return name, r, None
                except NeedsConfirmation as need:
                    need.tool_args = args
                    return name, None, need

            needs_confirm_hit = None
            if len(calls) > 1:
                with ThreadPoolExecutor(max_workers=min(len(calls), 4)) as executor:
                    futures = [executor.submit(_run_one, n, a) for n, a in calls]
                    for future in futures:
                        name, result, need = future.result()
                        if need is not None and needs_confirm_hit is None:
                            needs_confirm_hit = need
                            continue
                        if result is not None:
                            log.info("ran %s -> %r", name, result.message[:200])
                            messages.append({"role": "tool", "content": result.message, "tool_name": name})
                            results.append((name, result))
            else:
                name, args = calls[0]
                name_r, result, need = _run_one(name, args)
                if need is not None:
                    needs_confirm_hit = need
                elif result is not None:
                    log.info("ran %s -> %r", name_r, result.message[:200])
                    messages.append({"role": "tool", "content": result.message, "tool_name": name_r})
                    results.append((name_r, result))

            if needs_confirm_hit is not None:
                self.pending = (needs_confirm_hit.tool_name, needs_confirm_hit.tool_args, time.time())
                reply = _confirmation_message(needs_confirm_hit.tool_name, needs_confirm_hit.tool_args)
                break

            if finished:
                break

            # Only short-circuit to a raw tool result when it reflects a REAL
            # successful direct action. A blocked/skipped/refused/errored call
            # means the tool call itself was likely wrong (e.g. the model
            # misfired on a purely conversational message) — in that case we
            # must NOT return the skip message as the final answer. Instead
            # fall through and let the model take another turn, now seeing
            # the tool result, so it can respond naturally (e.g. actually
            # answer "how are you").
            def _is_real_action_result(result: ToolResult) -> bool:
                return result.status == "success"

            if results and all(n in DIRECT_REPLY_TOOLS for n, _ in results) and all(_is_real_action_result(r) for _, r in results):
                reply = "\n".join(r.message for _, r in results)
                break

        self._remember_turn_reply(reply)
        return reply

    def _remember_turn_reply(self, reply: str) -> None:
        self.history.append({"role": "assistant", "content": reply})

    def reset(self):
        self.history.clear()
        self.pending = None


agent = Agent()
