"""Tests for commander module."""
import subprocess
from unittest.mock import patch, MagicMock, call

from src.whisper_hotkey.commander import ask_claude, execute_command, run_command, _PROMPT_TEMPLATE

_RUN   = "src.whisper_hotkey.commander.subprocess.run"
_POPEN = "src.whisper_hotkey.commander.subprocess.Popen"


# ---------------------------------------------------------------------------
# ask_claude
# ---------------------------------------------------------------------------

def test_ask_claude_passes_print_flag_and_prompt():
    """CLI is called with ['claude', '--print', <prompt>]."""
    with patch(_RUN) as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="GUI: code\n", stderr="")
        ask_claude("open vs code")
    args = mock_run.call_args[0][0]
    assert args[0] == "claude"
    assert args[1] == "--print"
    assert "open vs code" in args[2]


def test_ask_claude_returns_stripped_response():
    with patch(_RUN) as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="  GUI: code  \n", stderr="")
        result = ask_claude("open vs code")
    assert result == "GUI: code"


def test_ask_claude_returns_none_on_nonzero_exit():
    with patch(_RUN) as mock_run:
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="error")
        result = ask_claude("something")
    assert result is None


def test_ask_claude_returns_none_on_empty_output():
    with patch(_RUN) as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="   ", stderr="")
        result = ask_claude("something")
    assert result is None


def test_ask_claude_returns_none_on_timeout():
    with patch(_RUN) as mock_run:
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="claude", timeout=15)
        result = ask_claude("something")
    assert result is None


def test_ask_claude_returns_none_on_oserror():
    with patch(_RUN) as mock_run:
        mock_run.side_effect = OSError("No such file or directory")
        result = ask_claude("something")
    assert result is None


def test_ask_claude_prompt_contains_whisper_service_name():
    with patch(_RUN) as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="GUI: code", stderr="")
        ask_claude("check status")
    prompt_arg = mock_run.call_args[0][0][2]
    assert "whisper-transcribe" in prompt_arg


# ---------------------------------------------------------------------------
# execute_command
# ---------------------------------------------------------------------------

def test_execute_command_gui_calls_popen_with_devnull():
    with patch(_POPEN) as mock_popen:
        result = execute_command("GUI: code")
    mock_popen.assert_called_once_with(
        ["code"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    assert result is True


def test_execute_command_terminal_calls_konsole():
    with patch(_POPEN) as mock_popen:
        result = execute_command("TERMINAL: systemctl status whisper-transcribe")
    mock_popen.assert_called_once_with(
        ["konsole", "--new-tab", "-e", "bash", "-c", "systemctl status whisper-transcribe"]
    )
    assert result is True


def test_execute_command_gui_case_insensitive():
    with patch(_POPEN) as mock_popen:
        result = execute_command("gui: code")
    assert result is True
    mock_popen.assert_called_once()


def test_execute_command_terminal_case_insensitive():
    with patch(_POPEN) as mock_popen:
        result = execute_command("terminal: htop")
    assert result is True
    mock_popen.assert_called_once()


def test_execute_command_gui_multi_word():
    with patch(_POPEN) as mock_popen:
        result = execute_command("GUI: dolphin --new-window /home")
    mock_popen.assert_called_once_with(
        ["dolphin", "--new-window", "/home"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    assert result is True


def test_execute_command_returns_false_on_unknown_format():
    result = execute_command("OPEN: something")
    assert result is False


def test_execute_command_gui_returns_false_on_popen_oserror():
    with patch(_POPEN) as mock_popen:
        mock_popen.side_effect = OSError("not found")
        result = execute_command("GUI: nonexistent-app")
    assert result is False


def test_execute_command_terminal_returns_false_on_popen_oserror():
    with patch(_POPEN) as mock_popen:
        mock_popen.side_effect = OSError("not found")
        result = execute_command("TERMINAL: htop")
    assert result is False


# ---------------------------------------------------------------------------
# run_command
# ---------------------------------------------------------------------------

def test_run_command_returns_false_when_ask_claude_fails():
    with patch("src.whisper_hotkey.commander.ask_claude", return_value=None):
        result = run_command("open vs code")
    assert result is False


def test_run_command_returns_false_when_execute_command_fails():
    with patch("src.whisper_hotkey.commander.ask_claude", return_value="GUI: code"), \
         patch("src.whisper_hotkey.commander.execute_command", return_value=False):
        result = run_command("open vs code")
    assert result is False


def test_run_command_returns_true_on_success():
    with patch("src.whisper_hotkey.commander.ask_claude", return_value="GUI: code"), \
         patch("src.whisper_hotkey.commander.execute_command", return_value=True):
        result = run_command("open vs code")
    assert result is True
