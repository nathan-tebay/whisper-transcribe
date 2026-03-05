"""Audio recording via pw-record (PipeWire) or parecord (PulseAudio)."""
import shutil
import signal
import subprocess
import time


def _detect_backend() -> str:
    """Return 'pipewire' or 'pulseaudio' based on available binaries."""
    if shutil.which("pw-record"):
        return "pipewire"
    if shutil.which("parecord"):
        return "pulseaudio"
    raise RuntimeError(
        "No audio recorder found. Install pipewire-utils (pw-record) "
        "or pulseaudio-utils (parecord)."
    )


class AudioRecorder:
    """Records audio to a WAV file using pw-record or parecord."""

    def __init__(self, output_path: str, sample_rate: int = 16000,
                 channels: int = 1, backend: str = "auto"):
        self.output_path = output_path
        self.sample_rate = sample_rate
        self.channels = channels
        self.backend = _detect_backend() if backend == "auto" else backend
        self._process = None
        self._start_time = None

    def _command(self) -> list[str]:
        if self.backend == "pipewire":
            return [
                "pw-record",
                "--rate", str(self.sample_rate),
                "--channels", str(self.channels),
                self.output_path,
            ]
        if self.backend == "pulseaudio":
            return [
                "parecord",
                f"--rate={self.sample_rate}",
                f"--channels={self.channels}",
                "--file-format=wav",
                self.output_path,
            ]
        raise RuntimeError(f"Unknown audio backend: {self.backend!r}")

    def start(self):
        """Start recording. Non-blocking. Raises RuntimeError if already recording."""
        if self._process is not None:
            raise RuntimeError("Recording already in progress")
        self._process = subprocess.Popen(self._command())
        self._start_time = time.monotonic()

    def stop(self) -> float:
        """Stop recording. Returns duration in seconds."""
        if self._process is None:
            return 0.0
        # SIGINT causes pw-record/parecord to flush and write correct WAV header sizes.
        # SIGTERM does not finalize the header, leaving data_size=0 which whisper.cpp rejects.
        self._process.send_signal(signal.SIGINT)
        self._process.wait()
        duration = time.monotonic() - self._start_time
        self._process = None
        self._start_time = None
        return duration
