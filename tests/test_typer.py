"""Tests for typer module."""
from unittest.mock import patch, MagicMock
from src.whisper_hotkey.typer import type_text

_PATCH = "src.whisper_hotkey.typer.subprocess.run"


def test_type_text_calls_ydotool():
    with patch(_PATCH) as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        type_text("hello world")
    mock_run.assert_called_once()
    args = mock_run.call_args[0][0]
    assert "ydotool" in args
    assert "hello world" in args


def test_type_text_returns_true_on_success():
    with patch(_PATCH) as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        result = type_text("hello")
    assert result is True


def test_type_text_returns_false_on_failure():
    with patch(_PATCH) as mock_run:
        mock_run.return_value = MagicMock(returncode=1)
        result = type_text("hello")
    assert result is False
