from fastapi import Header, HTTPException

from app.core import config


def require_api_secret(x_jarvis_secret: str = Header(default="")) -> None:
    expected = config.API_SECRET
    if expected.strip().lower() in {"", "changeme-set-a-real-secret-in-env", "paste-a-long-random-string-here"}:
        raise HTTPException(status_code=503, detail="API authentication is not configured.")
    if x_jarvis_secret != expected:
        raise HTTPException(status_code=401, detail="Invalid or missing X-Jarvis-Secret header.")
