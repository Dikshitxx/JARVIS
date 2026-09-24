import os
from dotenv import load_dotenv

load_dotenv()

MODEL_NAME = os.getenv("MODEL_NAME", "llama3.2:3b")
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
ASSISTANT_NAME = os.getenv("ASSISTANT_NAME", "Jarvis")
OWNER_NAME = os.getenv("OWNER_NAME", "Boss")

MAX_HISTORY_MESSAGES = 10   # keeps RAM/context small
NUM_CTX = 2048              # small context window for 8 GB RAM

from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[3] / "data"
ALLOWED_DIRS = [DATA_DIR]  # folders the assistant may read; add more deliberately later

PROJECT_ROOT = Path(__file__).resolve().parents[3]

ALLOWED_COMMANDS = [
	"python --version",
	"node --version",
	"npm --version",
	"git --version",
	"git status",
	"git branch",
	"git log --oneline -n 5",
	"pip list",
	"ollama list",
	"ollama ps",
]

DB_PATH = DATA_DIR / "jarvis.db"
MAX_MEMORIES_IN_PROMPT = 30

# name -> list of candidate executables (first one that exists is used)
ALLOWED_APPS = {
	"notepad": ["notepad.exe"],
	"calculator": ["calc.exe"],
	"explorer": ["explorer.exe"],
	"vscode": ["code", r"%LOCALAPPDATA%\Programs\Microsoft VS Code\Code.exe"],
	"brave": [
		r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
		r"%LOCALAPPDATA%\BraveSoftware\Brave-Browser\Application\brave.exe",
		"brave",
	],
}

BLOCKED_APP_TERMS = [
	"cmd", "command prompt", "powershell", "pwsh", "terminal", "regedit", "registry",
	"wsl", "bash", "windows security", "group policy", "task scheduler", "services",
	"uninstall", "setup", "installer",
]

SCREENSHOT_DIR = DATA_DIR / "screenshots"
