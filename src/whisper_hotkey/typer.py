"""Injects text into the focused window via ydotool."""
import logging
import subprocess

logger = logging.getLogger(__name__)


def type_text(text: str, timeout: int = 5) -> bool:
    """Type text into currently focused window. Returns True on success."""
    try:
        result = subprocess.run(
            ["ydotool", "type", "--", text],
            capture_output=True,
            timeout=timeout,
        )
        if result.returncode == 0:
            return True
        logger.error("ydotool failed (exit %d): %s", result.returncode,
                     result.stderr.decode(errors="replace"))
        return False
    except subprocess.TimeoutExpired:
        logger.error("ydotool timed out after %ds", timeout)
        return False
    except OSError as e:
        logger.error("Failed to invoke ydotool: %s", e)
        return False
