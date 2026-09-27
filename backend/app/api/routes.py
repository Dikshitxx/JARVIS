from fastapi import APIRouter
from fastapi import Depends
from pydantic import BaseModel

from app.agent.agent import agent
from app.api.auth import require_api_secret
from app.memory import store as memory_store
from app.tools.basic import get_system_info

router = APIRouter()


class ChatRequest(BaseModel):
    message: str


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


@router.post("/chat", dependencies=[Depends(require_api_secret)])
def chat(req: ChatRequest):
    return {"reply": agent.respond(req.message)}


@router.post("/reset", dependencies=[Depends(require_api_secret)])
def reset():
    agent.reset()
    return {"status": "history cleared"}
