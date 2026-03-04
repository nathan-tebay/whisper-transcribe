"""Tests for transcriber module."""
from unittest.mock import patch, MagicMock
from src.whisper_hotkey.transcriber import Transcriber

_PATCH = "src.whisper_hotkey.transcriber.subprocess.run"


def test_transcriber_calls_whisper_with_correct_args():
    with patch(_PATCH) as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=" Hello world\n", stderr="")
        t = Transcriber(binary="~/bin/whisper-main", model="~/bin/models/ggml-large-v3.bin")
        result = t.transcribe("/tmp/test.wav")
    assert result == "Hello world"
    args = mock_run.call_args[0][0]
    assert any("whisper" in a for a in args)
    assert "/tmp/test.wav" in args


def test_transcriber_returns_none_on_failure():
    with patch(_PATCH) as mock_run:
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="error")
        t = Transcriber(binary="~/bin/whisper-main", model="~/bin/models/ggml-large-v3.bin")
        result = t.transcribe("/tmp/test.wav")
    assert result is None


def test_transcriber_strips_whitespace():
    with patch(_PATCH) as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="  transcribed text  \n", stderr="")
        t = Transcriber(binary="~/bin/whisper-main", model="~/bin/models/ggml-large-v3.bin")
        result = t.transcribe("/tmp/test.wav")
    assert result == "transcribed text"


def test_transcriber_returns_none_on_empty_output():
    with patch(_PATCH) as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="   \n", stderr="")
        t = Transcriber(binary="~/bin/whisper-main", model="~/bin/models/ggml-large-v3.bin")
        result = t.transcribe("/tmp/test.wav")
    assert result is None


def test_transcriber_returns_none_on_timeout():
    """A hung whisper.cpp process must return None, not block forever."""
    import subprocess as _subprocess
    with patch(_PATCH) as mock_run:
        mock_run.side_effect = _subprocess.TimeoutExpired(cmd="whisper-main", timeout=60)
        t = Transcriber(binary="~/bin/whisper-main", model="~/bin/models/ggml-large-v3.bin")
        result = t.transcribe("/tmp/test.wav")
    assert result is None
