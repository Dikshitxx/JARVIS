from fastapi import FastAPI

from app.api.routes import router

app = FastAPI(title="Jarvis Agent Core")
app.include_router(router)
