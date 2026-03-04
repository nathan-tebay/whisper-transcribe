"""Transcription via whisper.cpp subprocess."""
import os
import subprocess


class Transcriber:
    """Wraps whisper.cpp binary for audio transcription."""

    def __init__(self, binary: str, model: str, language: str = "en"):
        self.binary = os.path.expanduser(binary)
        self.model = os.path.expanduser(model)
        self.language = language

    def transcribe(self, audio_path: str) -> str | None:
        """Transcribe audio file. Returns text or None on failure."""
        result = subprocess.run(
            [
                self.binary,
                "-m", self.model,
                "-f", audio_path,
                "--no-timestamps",
                "-np",          # no progress output
                "-l", self.language,
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return None
        text = result.stdout.strip()
        return text if text else None
