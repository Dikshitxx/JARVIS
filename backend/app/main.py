from contextlib import asynccontextmanager

from app.core.logging_setup import setup_logging
setup_logging()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.core.config import settings
from app.tools.browser_session import shutdown_browser_session


@asynccontextmanager
async def lifespan(_app: FastAPI):
	yield
	shutdown_browser_session()

app = FastAPI(title="Jarvis Agent Core", lifespan=lifespan)
app.add_middleware(
	CORSMiddleware,
	allow_origins=[origin.strip() for origin in settings.FRONTEND_ORIGINS.split(",") if origin.strip()],
	allow_methods=["GET", "POST"],
	allow_headers=["Content-Type", "X-Jarvis-Secret"],
)
app.include_router(router)
