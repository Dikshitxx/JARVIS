from app.core.logging_setup import setup_logging
setup_logging()

from fastapi import FastAPI

from app.api.routes import router

app = FastAPI(title="Jarvis Agent Core")
app.include_router(router)
