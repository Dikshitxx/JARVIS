from datetime import datetime

from PIL import ImageGrab

from app.core import config
from app.tools.registry import Tool, register

MAX_SCREENSHOTS = 20


def _cleanup_old_screenshots():
    files = sorted(config.SCREENSHOT_DIR.glob("screenshot_*.png"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old_file in files[MAX_SCREENSHOTS:]:
        try:
            old_file.unlink()
        except OSError:
            pass


def take_screenshot() -> str:
    config.SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    path = config.SCREENSHOT_DIR / f"screenshot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
    image = ImageGrab.grab(all_screens=True)
    image.save(path)
    _cleanup_old_screenshots()
    return f"Screenshot saved: {path} ({image.width}x{image.height})"


register(Tool(
    name="take_screenshot",
    description="Take a screenshot of the user's screen and save it to a file. This needs the user's confirmation.",
    parameters={"type": "object", "properties": {}},
    func=take_screenshot,
    risk="confirm",
))
