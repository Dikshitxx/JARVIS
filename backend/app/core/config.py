import os
from dotenv import load_dotenv

load_dotenv()

MODEL_NAME = os.getenv("MODEL_NAME", "llama3.2:3b")
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
ASSISTANT_NAME = os.getenv("ASSISTANT_NAME", "Jarvis")
OWNER_NAME = os.getenv("OWNER_NAME", "Boss")

MAX_HISTORY_MESSAGES = 10   # keeps RAM/context small
NUM_CTX = 2048              # small context window for 8 GB RAM
