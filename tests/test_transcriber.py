"""Tests for transcriber module."""
from unittest.mock import patch, MagicMock
from src.whisper_hotkey.transcriber import Transcriber


def test_transcriber_calls_whisper_with_correct_args():
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=" Hello world\n", stderr="")
        t = Transcriber(binary="~/bin/whisper-main", model="~/bin/models/ggml-large-v3.bin")
        result = t.transcribe("/tmp/test.wav")
    assert result == "Hello world"
    args = mock_run.call_args[0][0]
    assert any("whisper" in a for a in args)
    assert "/tmp/test.wav" in args


def test_transcriber_returns_none_on_failure():
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="error")
        t = Transcriber(binary="~/bin/whisper-main", model="~/bin/models/ggml-large-v3.bin")
        result = t.transcribe("/tmp/test.wav")
    assert result is None


def test_transcriber_strips_whitespace():
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="  transcribed text  \n", stderr="")
        t = Transcriber(binary="~/bin/whisper-main", model="~/bin/models/ggml-large-v3.bin")
        result = t.transcribe("/tmp/test.wav")
    assert result == "transcribed text"


def test_transcriber_returns_none_on_empty_output():
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="   \n", stderr="")
        t = Transcriber(binary="~/bin/whisper-main", model="~/bin/models/ggml-large-v3.bin")
        result = t.transcribe("/tmp/test.wav")
    assert result is None
