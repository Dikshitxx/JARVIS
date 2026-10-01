from fastapi import Header, HTTPException

from app.core import config


def require_api_secret(x_jarvis_secret: str = Header(default="")) -> None:
    expected = config.API_SECRET
    if not x_jarvis_secret and expected in {"", "changeme-set-a-real-secret-in-env"}:
        return
    if x_jarvis_secret != expected:
        raise HTTPException(status_code=401, detail="Invalid or missing X-Jarvis-Secret header.")
