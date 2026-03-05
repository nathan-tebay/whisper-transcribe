"""Injects text and key events into the focused window via ydotool."""
import logging
import subprocess

logger = logging.getLogger(__name__)


def _run_ydotool(*args: str, timeout: int = 5) -> bool:
    """Run ydotool with the given arguments. Returns True on success."""
    try:
        result = subprocess.run(
            ["ydotool", *args],
            capture_output=True,
            timeout=timeout,
        )
        if result.returncode == 0:
            return True
        logger.error("ydotool %s failed (exit %d): %s",
                     args[0], result.returncode,
                     result.stderr.decode(errors="replace"))
        return False
    except subprocess.TimeoutExpired:
        logger.error("ydotool timed out after %ds", timeout)
        return False
    except OSError as e:
        logger.error("Failed to invoke ydotool: %s", e)
        return False


def type_text(text: str, timeout: int = 5) -> bool:
    """Type text into currently focused window. Returns True on success."""
    return _run_ydotool("type", "--", text, timeout=timeout)


def press_return(timeout: int = 5) -> bool:
    """Send a Return keypress. Returns True on success."""
    return _run_ydotool("key", "--key-delay", "50", "28:1", "28:0", timeout=timeout)
