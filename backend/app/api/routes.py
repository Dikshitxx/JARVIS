from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.agent.agent import agent
from app.api.auth import require_api_secret
from app.memory import store as memory_store
from app.tools.basic import get_system_info
from app.voice import voice_service
from app.tasks import TaskCapacityError, normalize_task_status, task_manager
from app.agent.utterance import analyze_utterance
from app.agent import runtime_context

router = APIRouter()


class ChatRequest(BaseModel):
    message: str
    background: bool = False


@router.get("/health")
def health():
    return {"status": "ok"}


@router.get("/status")
def status():
    return {"info": get_system_info()}


@router.get("/activity")
def activity():
    rows = memory_store.recent_tool_executions(limit=8)
    return {
        "items": [
            {"tool": r[0], "args": r[1], "success": bool(r[4]), "time": r[5]}
            for r in rows
        ]
    }


@router.get("/voice/status")
def voice_status():
    return voice_service.status()


@router.post("/chat", dependencies=[Depends(require_api_secret)])
def chat(req: ChatRequest):
    analysis = analyze_utterance(
        req.message,
        runtime_context.get_context(),
        has_pending=agent.pending is not None,
    )
    if analysis.cancellation and agent.pending is None:
        cancelled = task_manager.cancel_latest()
        if cancelled:
            return {
                "status": "CANCELLED",
                "reply": "Cancellation requested. JARVIS will stop after the current operation finishes.",
            }
    try:
        if req.background:
            task_id = task_manager.submit(req.message)
            return {
                "task_id": task_id,
                "status": "QUEUED",
                "reply": "I’m working on that in the background.",
            }
        task_id, reply = task_manager.run_sync(req.message)
        task = task_manager.task(task_id) or {}
        status = normalize_task_status(task.get("status", "FAILED"))
        return {"task_id": task_id, "status": status, "reply": reply}
    except TaskCapacityError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc


@router.get("/tasks", dependencies=[Depends(require_api_secret)])
def list_tasks():
    return {"items": task_manager.list_recent()}


@router.get("/tasks/{task_id}", dependencies=[Depends(require_api_secret)])
def task_status(task_id: str):
    task = task_manager.task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found.")
    return task


@router.post("/tasks/{task_id}/cancel", dependencies=[Depends(require_api_secret)])
def cancel_task(task_id: str):
    task = task_manager.cancel(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found.")
    return task_manager.task(task_id) or task


@router.post("/reset", dependencies=[Depends(require_api_secret)])
def reset():
    task_manager.cancel_all()
    agent.reset()
    return {"status": "history cleared"}
