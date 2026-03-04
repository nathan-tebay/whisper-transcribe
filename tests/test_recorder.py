"""Tests for recorder module."""
import time
from unittest.mock import MagicMock, patch
from src.whisper_hotkey.recorder import AudioRecorder


def test_recorder_starts_pw_record_on_start():
    with patch("subprocess.Popen") as mock_popen:
        mock_popen.return_value = MagicMock()
        rec = AudioRecorder(output_path="/tmp/test.wav", sample_rate=16000)
        rec.start()
    mock_popen.assert_called_once()
    args = mock_popen.call_args[0][0]
    assert "pw-record" in args
    assert "/tmp/test.wav" in args


def test_recorder_stop_kills_process():
    with patch("subprocess.Popen") as mock_popen:
        mock_proc = MagicMock()
        mock_popen.return_value = mock_proc
        rec = AudioRecorder(output_path="/tmp/test.wav")
        rec.start()
        rec.stop()
    mock_proc.terminate.assert_called_once()
    mock_proc.wait.assert_called_once()


def test_recorder_duration_is_short_when_quick():
    with patch("subprocess.Popen") as mock_popen:
        mock_popen.return_value = MagicMock()
        rec = AudioRecorder(output_path="/tmp/test.wav")
        rec.start()
        # Don't sleep — stop immediately
        duration = rec.stop()
    assert duration < 0.5


def test_recorder_not_started_stop_is_noop():
    rec = AudioRecorder(output_path="/tmp/test.wav")
    duration = rec.stop()  # Should not raise
    assert duration == 0.0
