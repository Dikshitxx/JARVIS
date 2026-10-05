import os
from pathlib import Path

import uvicorn

BACKEND_DIR = Path(__file__).resolve().parents[1]


def main() -> None:
    os.chdir(BACKEND_DIR)
    uvicorn.run("app.main:app", app_dir=str(BACKEND_DIR), reload=True)
