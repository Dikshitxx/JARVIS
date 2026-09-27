from fastapi import Header, HTTPException

from app.core import config


def require_api_secret(x_jarvis_secret: str = Header(default="")) -> None:
    if x_jarvis_secret != config.API_SECRET:
        raise HTTPException(status_code=401, detail="Invalid or missing X-Jarvis-Secret header.")
