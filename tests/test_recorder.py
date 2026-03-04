"""Tests for recorder module."""
import pytest
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
        duration = rec.stop()
    assert duration < 0.5


def test_recorder_not_started_stop_is_noop():
    rec = AudioRecorder(output_path="/tmp/test.wav")
    duration = rec.stop()
    assert duration == 0.0


def test_recorder_double_start_raises():
    """Calling start() twice without stop() must raise RuntimeError."""
    with patch("subprocess.Popen") as mock_popen:
        mock_popen.return_value = MagicMock()
        rec = AudioRecorder(output_path="/tmp/test.wav")
        rec.start()
        with pytest.raises(RuntimeError, match="already in progress"):
            rec.start()


def test_recorder_stop_clears_state():
    """After stop(), process and start_time must be None."""
    with patch("subprocess.Popen") as mock_popen:
        mock_popen.return_value = MagicMock()
        rec = AudioRecorder(output_path="/tmp/test.wav")
        rec.start()
        rec.stop()
    assert rec._process is None
    assert rec._start_time is None


def test_recorder_start_failure_keeps_state_clean():
    """If Popen raises, _process and _start_time must remain None."""
    with patch("subprocess.Popen") as mock_popen:
        mock_popen.side_effect = FileNotFoundError("pw-record not found")
        rec = AudioRecorder(output_path="/tmp/test.wav")
        with pytest.raises(FileNotFoundError):
            rec.start()
    assert rec._process is None
    assert rec._start_time is None
    # stop() must still be safe to call
    assert rec.stop() == 0.0
