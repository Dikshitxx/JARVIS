# Jarvis: engineering rules for Copilot

## Project
Jarvis is a local personal assistant: FastAPI backend (Python, `app/`), Next.js frontend, Ollama locally (llama3.2:3b), Windows desktop. Cloud LLMs (Gemini, Groq) are reached through OpenAI-compatible endpoints in `app/llm/llm.py`.

## Hard rules (never violate)
- Never hardcode, print, or log API keys, secrets, or full prompts. Secrets come from env vars via python-dotenv only.
- Private requests (`private=True`) must never reach a cloud provider.
- All files UTF-8. If you see mojibake (`â€`, `Ã`), fix it.
- Permissions are decided by fixed code (`classify.py`), never by an LLM. LLMs decide what the user means; code decides what is allowed and whether it succeeded.
- Task and tool status (SUCCEEDED/FAILED/UNVERIFIED/BLOCKED) derives only from `ToolResult.status` and `verification_status`, never from model-generated text.
- The Jarvis UI window ("JARVIS | System Interface") and its process tree must never be closed or killed by any tool.

## Scope discipline
- Smallest diff that satisfies the task. No drive-by refactors, renames, formatting sweeps, or file moves.
- Preserve public function signatures and return shapes unless the task says to change them. If you must change one, update every call site in the same change.
- Do not add dependencies without listing them in your plan first.
- Do not touch files outside the current stage's list.

## Code quality
- Type hints on new functions. Narrow `except` clauses; never `except: pass`. Log with the `jarvis.*` logger, no `print`.
- No TODO stubs, placeholder returns, or fake data. If something cannot be implemented, say so.
- Intent routing uses model judgment, not keyword/regex lists. Regex is allowed only for output cleanup, security validation, and parsing model JSON.
- Every LLM call that can fail needs a fallback path and a timeout.

## Process
- Plan before editing: list files to change, the change per file, risks. Then wait for "go" unless told to proceed.
- Work one stage at a time. After each stage: the app must import and start, existing tests must pass, new tests must pass.
- Tests mock all network, browser, and LLM calls. Never weaken or delete an existing test to make it pass.
- If a requirement is ambiguous or a file is missing, state your assumption explicitly in the plan. Do not silently guess.
- End every stage with: changed files + reason, tests run + result, assumptions, anything deferred or blocked.