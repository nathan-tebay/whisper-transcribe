"""Natural-language command execution via Claude CLI."""
import logging
import shlex
import subprocess

logger = logging.getLogger(__name__)

CLAUDE_CLI     = "claude"
CLAUDE_TIMEOUT = 15  # seconds

_PROMPT_TEMPLATE = (
    "Convert the following spoken command to a shell command for KDE Plasma on Fedora Linux.\n"
    "Reply with EXACTLY ONE LINE in one of these two formats:\n"
    "  GUI: <command>       (for apps that open a window and run in background)\n"
    "  TERMINAL: <command>  (for commands that produce output needing a terminal)\n"
    "Do not explain. Do not add punctuation after the command.\n"
    'Context: the whisper transcription daemon systemd service is named "whisper-transcribe".\n'
    "Command: {natural_language}"
)


def ask_claude(natural_language: str) -> str | None:
    """Call Claude CLI; return stripped single-line response or None on failure."""
    prompt = _PROMPT_TEMPLATE.format(natural_language=natural_language)
    try:
        result = subprocess.run(
            [CLAUDE_CLI, "--print", prompt],
            capture_output=True, text=True, timeout=CLAUDE_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        logger.error("Claude CLI timed out after %ds", CLAUDE_TIMEOUT)
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
    return response


def execute_command(response: str) -> bool:
    """Parse 'GUI: cmd' or 'TERMINAL: cmd' and execute. Returns True if launched."""
    if response.upper().startswith("GUI:"):
        cmd = response[4:].strip()
        logger.info("Executing GUI command: %r", cmd)
        try:
            subprocess.Popen(shlex.split(cmd), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except OSError as e:
            logger.error("Failed to launch GUI command %r: %s", cmd, e)
            return False

    if response.upper().startswith("TERMINAL:"):
        cmd = response[9:].strip()
        logger.info("Executing terminal command: %r", cmd)
        try:
            subprocess.Popen(["konsole", "--new-tab", "-e", "bash", "-c", cmd])
            return True
        except OSError as e:
            logger.error("Failed to launch terminal command %r: %s", cmd, e)
            return False

    logger.error("Unexpected Claude response format: %r", response)
    return False


def run_command(natural_language: str) -> bool:
    """Full pipeline: interpret with Claude, then execute. Returns True on success."""
    response = ask_claude(natural_language)
    if response is None:
        return False
    return execute_command(response)
