"""Injects text into the focused window via ydotool."""
import subprocess


def type_text(text: str) -> bool:
    """Type text into currently focused window. Returns True on success."""
    result = subprocess.run(
        ["ydotool", "type", "--", text],
        capture_output=True,
    )
    return result.returncode == 0
