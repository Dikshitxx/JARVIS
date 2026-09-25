import logging
from logging.handlers import RotatingFileHandler

from app.core import config


def setup_logging() -> None:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    log_dir = config.DATA_DIR / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger("jarvis")
    if root.handlers:
        return  # already configured
    root.setLevel(logging.INFO)

    fmt = logging.Formatter("[%(asctime)s] %(levelname)s %(name)s: %(message)s", datefmt="%H:%M:%S")

    file_handler = RotatingFileHandler(log_dir / "jarvis.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    file_handler.setFormatter(fmt)
    root.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(fmt)
    root.addHandler(console_handler)
