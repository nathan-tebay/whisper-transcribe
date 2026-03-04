"""Audio recording via pw-record (PipeWire)."""
import subprocess
import time


class AudioRecorder:
    """Records audio to a WAV file using pw-record."""

    def __init__(self, output_path: str, sample_rate: int = 16000, channels: int = 1):
        self.output_path = output_path
        self.sample_rate = sample_rate
        self.channels = channels
        self._process = None
        self._start_time = None

    def start(self):
        """Start recording. Non-blocking. Raises RuntimeError if already recording."""
        if self._process is not None:
            raise RuntimeError("Recording already in progress")
        # Assign process first; _start_time only set on successful Popen
        self._process = subprocess.Popen([
            "pw-record",
            "--rate", str(self.sample_rate),
            "--channels", str(self.channels),
            self.output_path,
        ])
        self._start_time = time.monotonic()

    def stop(self) -> float:
        """Stop recording. Returns duration in seconds."""
        if self._process is None:
            return 0.0
        self._process.terminate()
        self._process.wait()
        duration = time.monotonic() - self._start_time
        self._process = None
        self._start_time = None
        return duration
