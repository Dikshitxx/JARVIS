import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).parent / "backend"
VENV_PYTHON = BACKEND / ".venv" / "Scripts" / "python.exe"

if not VENV_PYTHON.exists():
    print(f"ERROR: venv Python not found at {VENV_PYTHON}")
    sys.exit(1)

subprocess.run(
    [str(VENV_PYTHON), "-m", "uvicorn", "app.main:app", "--reload"],
    cwd=BACKEND,
)
