"""Natural-language command execution via Claude CLI or local Ollama."""
import json
import logging
import os
import shlex
import subprocess
import urllib.error
import urllib.request

from . import config as _config

logger = logging.getLogger(__name__)

_PROMPT_TEMPLATE = (
    "Convert the following spoken command into one of the response formats below.\n"
    "Reply with EXACTLY ONE LINE. Do not explain.\n"
    "\n"
    "Formats:\n"
    "  GUI: <command>            (open an app or URL in the background)\n"
    "  TERMINAL: <command>       (run a shell command in a terminal window)\n"
    "  KEYS: <ydotool-sequence>  (send keystrokes; use keycode:1 keycode:0 pairs)\n"
    "\n"
    "KEYS format rules:\n"
    "  - Each key event is keycode:1 (press) followed by keycode:0 (release)\n"
    "  - Hold modifiers by pressing before and releasing after: 29:1 30:1 30:0 29:0 = Ctrl+A\n"
    "  - Repeat keys by repeating the press/release pair\n"
    "  - Common keycodes: backspace=14, tab=15, enter=28, esc=1, delete=111,\n"
    "    space=57, home=102, end=107, pgup=104, pgdn=109,\n"
    "    left=105, right=106, up=103, down=108,\n"
    "    ctrl=29, shift=42, alt=56\n"
    "  - Ctrl+Z=undo, Ctrl+Y=redo, Ctrl+A=select all, Ctrl+C=copy, Ctrl+V=paste,\n"
    "    Ctrl+X=cut, Ctrl+Backspace=delete word, Shift+Home=select to line start,\n"
    "    Shift+End=select to line end\n"
    "\n"
    "GUI/TERMINAL rules:\n"
    "  - To open a website: GUI: xdg-open https://...\n"
    "  - To open a file manager at a path: GUI: dolphin /some/path\n"
    "  - Use full paths, never ~\n"
    "\n"
    "Context:\n"
    "  User home directory: {home}\n"
    '  Systemd service name: "whisper-transcribe"\n'
    "\n"
    "Examples:\n"
    '  "open linkedin"                   -> GUI: xdg-open https://www.linkedin.com\n'
    '  "open dolphin in downloads"       -> GUI: dolphin {home}/Downloads\n'
    '  "show disk usage"                 -> TERMINAL: df -h\n'
    '  "backspace"                       -> KEYS: 14:1 14:0\n'
    '  "backspace five times"            -> KEYS: 14:1 14:0 14:1 14:0 14:1 14:0 14:1 14:0 14:1 14:0\n'
    '  "tab three times"                 -> KEYS: 15:1 15:0 15:1 15:0 15:1 15:0\n'
    '  "select all"                      -> KEYS: 29:1 30:1 30:0 29:0\n'
    '  "undo"                            -> KEYS: 29:1 44:1 44:0 29:0\n'
    '  "delete last word"                -> KEYS: 29:1 14:1 14:0 29:0\n'
    '  "select to start of line"         -> KEYS: 42:1 102:1 102:0 42:0\n'
    '  "delete to start of line"         -> KEYS: 42:1 102:1 102:0 42:0 14:1 14:0\n'
    "\n"
    "Command: {natural_language}"
)


def _build_prompt(natural_language: str) -> str:
    return _PROMPT_TEMPLATE.format(
        natural_language=natural_language,
        home=os.path.expanduser("~"),
    )


def ask_ollama(natural_language: str, cfg: dict) -> str | None:
    """Send prompt to local Ollama; return single-line response or None on failure."""
    model   = os.environ.get("WHISPER_OLLAMA_MODEL", cfg["ollama_model"])
    url     = cfg["ollama_url"]
    timeout = cfg["ollama_timeout"]
    payload = json.dumps({
        "model": model,
        "prompt": _build_prompt(natural_language),
        "stream": False,
    }).encode()
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
    except urllib.error.URLError as e:
        logger.error("Ollama request failed: %s", e)
        return None
    except TimeoutError:
        logger.error("Ollama timed out after %ds", timeout)
        return None

    response = data.get("response", "").strip()
    if not response:
        logger.error("Ollama returned empty response")
        return None
    # Take only the first line in case the model adds explanation
    return response.splitlines()[0].strip()


def ask_claude(natural_language: str, cfg: dict) -> str | None:
    """Call Claude CLI; return stripped single-line response or None on failure."""
    timeout = cfg["claude_timeout"]
    try:
        result = subprocess.run(
            ["claude", "--print", _build_prompt(natural_language)],
            capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        logger.error("Claude CLI timed out after %ds", timeout)
        return None
    except OSError as e:
        logger.error("Failed to invoke Claude CLI: %s", e)
        return None

    if result.returncode != 0:
        logger.error("Claude CLI failed (exit %d): %s", result.returncode, result.stderr.strip())
        return None

    response = result.stdout.strip()
    if not response:
        logger.error("Claude CLI returned empty response")
        return None
    return response.splitlines()[0].strip()


def execute_command(response: str, cfg: dict) -> bool:
    """Parse 'GUI: cmd' or 'TERMINAL: cmd' and execute. Returns True if launched."""
    if response.upper().startswith("GUI:"):
        cmd = response[4:].strip()
        logger.info("Executing GUI command: %r", cmd)
        try:
            cmd_parts = shlex.split(cmd)
        except ValueError as e:
            logger.error("Failed to parse GUI command %r: %s", cmd, e)
            return False
        try:
            subprocess.Popen(cmd_parts, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except OSError as e:
            logger.error("Failed to launch GUI command %r: %s", cmd, e)
            return False

    if response.upper().startswith("TERMINAL:"):
        cmd = response[9:].strip()
        logger.info("Executing terminal command: %r", cmd)
        try:
            terminal_parts = shlex.split(cfg["terminal_command"])
            subprocess.Popen(terminal_parts + [cmd])
            return True
        except OSError as e:
            logger.error("Failed to launch terminal command %r: %s", cmd, e)
            return False

    if response.upper().startswith("KEYS:"):
        from .typer import press_keys
        sequence = response[5:].strip()
        logger.info("Sending key sequence: %r", sequence)
        return press_keys(sequence)

    logger.error("Unexpected response format: %r", response)
    return False


def run_command(natural_language: str) -> bool:
    """Full pipeline: interpret with selected backend, then execute."""
    cfg     = _config.load()
    backend = os.environ.get("WHISPER_COMMAND_BACKEND", cfg["command_backend"])

    if backend == "claude":
        response = ask_claude(natural_language, cfg)
    else:
        response = ask_ollama(natural_language, cfg)

    if response is None:
        return False
    return execute_command(response, cfg)
