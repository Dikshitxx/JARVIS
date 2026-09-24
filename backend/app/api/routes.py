from fastapi import APIRouter
from pydantic import BaseModel

from app.agent.agent import agent

router = APIRouter()


class ChatRequest(BaseModel):
    message: str


@router.get("/health")
def health():
    return {"status": "ok"}


@router.post("/chat")
def chat(req: ChatRequest):
    return {"reply": agent.respond(req.message)}


@router.post("/reset")
def reset():
    agent.reset()
    return {"status": "history cleared"}
