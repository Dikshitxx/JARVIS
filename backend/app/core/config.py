from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    MODEL_NAME: str = "llama3.2:3b"
    VISION_MODEL: str = "moondream"
    OLLAMA_HOST: str = "http://localhost:11434"
    OLLAMA_KEEP_ALIVE: str = "30m"
    ASSISTANT_NAME: str = "Jarvis"
    OWNER_NAME: str = "Boss"
    API_SECRET: str = "jarvis-local-dev-secret-change-me"
    FRONTEND_ORIGINS: str = "http://localhost:3000,http://127.0.0.1:3000"

    MAX_HISTORY_MESSAGES: int = 10
    NUM_CTX: int = 8192
    MAX_MEMORIES_IN_PROMPT: int = 30
    BROWSER_EXECUTABLE_PATH: str = ""
    BROWSER_PATH: str = r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe"
    BROWSER_CHANNEL: str = ""
    BROWSER_PROFILE_DIR: str = "browser_profile"
    BROWSER_HEADLESS: bool = False
    BROWSER_NAVIGATION_TIMEOUT: int = 20000
    BROWSER_INTERACTION_TIMEOUT: int = 10000
    BROWSER_SEARCH_PROVIDER: str = "https://www.google.com/search?q={query}"
    WEB_SEARCH_PROVIDER: str = "auto"
    WEB_SEARCH_TIMEOUT_SECONDS: int = 8
    WEB_SEARCH_RESULT_LIMIT: int = 10
    VOICE_ENABLED: bool = True
    VOICE_WAKE_WORD: str = "hey_jarvis"
    VOICE_WAKE_THRESHOLD: float = 0.5
    VOICE_VAD_MODE: int = 2
    VOICE_END_SILENCE_MS: int = 720
    VOICE_NO_SPEECH_TIMEOUT_SECONDS: int = 8
    VOICE_MAX_COMMAND_SECONDS: int = 30
    VOICE_STT_MODEL: str = "tiny"
    VOICE_STT_CPU_THREADS: int = 2
    VOICE_INPUT_DEVICE: str = ""
    VOICE_TTS_RATE: int = 175


settings = Settings()

# Backward-compatible module-level names (existing code imports these directly)
MODEL_NAME = settings.MODEL_NAME
VISION_MODEL = settings.VISION_MODEL
OLLAMA_HOST = settings.OLLAMA_HOST
OLLAMA_KEEP_ALIVE = settings.OLLAMA_KEEP_ALIVE
ASSISTANT_NAME = settings.ASSISTANT_NAME
OWNER_NAME = settings.OWNER_NAME
API_SECRET = settings.API_SECRET
FRONTEND_ORIGINS = settings.FRONTEND_ORIGINS
MAX_HISTORY_MESSAGES = settings.MAX_HISTORY_MESSAGES
NUM_CTX = settings.NUM_CTX
MAX_MEMORIES_IN_PROMPT = settings.MAX_MEMORIES_IN_PROMPT
BROWSER_EXECUTABLE_PATH = settings.BROWSER_EXECUTABLE_PATH
BROWSER_PATH = settings.BROWSER_PATH
BROWSER_CHANNEL = settings.BROWSER_CHANNEL
BROWSER_PROFILE_DIR = settings.BROWSER_PROFILE_DIR
BROWSER_HEADLESS = settings.BROWSER_HEADLESS
BROWSER_NAVIGATION_TIMEOUT = settings.BROWSER_NAVIGATION_TIMEOUT
BROWSER_INTERACTION_TIMEOUT = settings.BROWSER_INTERACTION_TIMEOUT
BROWSER_SEARCH_PROVIDER = settings.BROWSER_SEARCH_PROVIDER
WEB_SEARCH_PROVIDER = settings.WEB_SEARCH_PROVIDER
WEB_SEARCH_TIMEOUT_SECONDS = settings.WEB_SEARCH_TIMEOUT_SECONDS
WEB_SEARCH_RESULT_LIMIT = settings.WEB_SEARCH_RESULT_LIMIT
VOICE_ENABLED = settings.VOICE_ENABLED
VOICE_WAKE_WORD = settings.VOICE_WAKE_WORD
VOICE_WAKE_THRESHOLD = settings.VOICE_WAKE_THRESHOLD
VOICE_VAD_MODE = settings.VOICE_VAD_MODE
VOICE_END_SILENCE_MS = settings.VOICE_END_SILENCE_MS
VOICE_NO_SPEECH_TIMEOUT_SECONDS = settings.VOICE_NO_SPEECH_TIMEOUT_SECONDS
VOICE_MAX_COMMAND_SECONDS = settings.VOICE_MAX_COMMAND_SECONDS
VOICE_STT_MODEL = settings.VOICE_STT_MODEL
VOICE_STT_CPU_THREADS = settings.VOICE_STT_CPU_THREADS
VOICE_INPUT_DEVICE = settings.VOICE_INPUT_DEVICE
VOICE_TTS_RATE = settings.VOICE_TTS_RATE

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
    "edge": [
        r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe",
        r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe",
        r"%LOCALAPPDATA%\Microsoft\Edge\Application\msedge.exe",
        "msedge",
    ],
}

BLOCKED_APP_TERMS = [
    "cmd", "command prompt", "powershell", "pwsh", "terminal", "regedit", "registry",
    "wsl", "bash", "windows security", "group policy", "task scheduler", "services",
    "uninstall", "setup", "installer",
]
