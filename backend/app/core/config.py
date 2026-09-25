from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    MODEL_NAME: str = "llama3.2:3b"
    OLLAMA_HOST: str = "http://localhost:11434"
    ASSISTANT_NAME: str = "Jarvis"
    OWNER_NAME: str = "Boss"

    MAX_HISTORY_MESSAGES: int = 10
    NUM_CTX: int = 2048
    MAX_MEMORIES_IN_PROMPT: int = 30


settings = Settings()

# Backward-compatible module-level names (existing code imports these directly)
MODEL_NAME = settings.MODEL_NAME
OLLAMA_HOST = settings.OLLAMA_HOST
ASSISTANT_NAME = settings.ASSISTANT_NAME
OWNER_NAME = settings.OWNER_NAME
MAX_HISTORY_MESSAGES = settings.MAX_HISTORY_MESSAGES
NUM_CTX = settings.NUM_CTX
MAX_MEMORIES_IN_PROMPT = settings.MAX_MEMORIES_IN_PROMPT

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = PROJECT_ROOT / "data"
DB_PATH = DATA_DIR / "jarvis.db"
SCREENSHOT_DIR = DATA_DIR / "screenshots"

ALLOWED_DIRS = [DATA_DIR]

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
