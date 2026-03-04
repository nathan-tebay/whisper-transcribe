"""Tests for typer module."""
import subprocess
from unittest.mock import patch, MagicMock
from src.whisper_hotkey.typer import type_text

_PATCH = "src.whisper_hotkey.typer.subprocess.run"


def test_type_text_calls_ydotool_with_separator():
    """Verify exact args including -- separator."""
    with patch(_PATCH) as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        type_text("hello world")
    mock_run.assert_called_once()
    args = mock_run.call_args[0][0]
    assert args == ["ydotool", "type", "--", "hello world"]


def test_type_text_returns_true_on_success():
    with patch(_PATCH) as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        result = type_text("hello")
    assert result is True


def test_type_text_returns_false_on_failure():
    with patch(_PATCH) as mock_run:
        mock_run.return_value = MagicMock(returncode=1, stderr=b"error")
        result = type_text("hello")
    assert result is False


def test_type_text_handles_leading_dash():
    """Text starting with - must not be misinterpreted as a flag."""
    with patch(_PATCH) as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        type_text("-flag-like-text")
    args = mock_run.call_args[0][0]
    assert args == ["ydotool", "type", "--", "-flag-like-text"]


def test_type_text_returns_false_on_timeout():
    """ydotoold hang must return False without blocking."""
    with patch(_PATCH) as mock_run:
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="ydotool", timeout=5)
        result = type_text("hello")
    assert result is False


def test_type_text_returns_false_on_oserror():
    """Missing ydotool binary must return False."""
    with patch(_PATCH) as mock_run:
        mock_run.side_effect = OSError("No such file or directory")
        result = type_text("hello")
    assert result is False
