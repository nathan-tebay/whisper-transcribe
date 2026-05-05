"""Transcription via whisper.cpp subprocess."""
import logging
import os
import subprocess

logger = logging.getLogger(__name__)


class Transcriber:
    """Wraps whisper.cpp binary for audio transcription."""

    def __init__(self, binary: str, model: str, language: str = "en",
                 gpu: bool = True):
        self.binary = os.path.expanduser(binary)
        self.model = os.path.expanduser(model)
        self.language = language
        self.gpu = gpu

    def transcribe(self, audio_path: str, timeout: int = 60) -> str | None:
        """Transcribe audio file. Returns text or None on failure/timeout."""
        try:
            cmd = [
                self.binary,
                "-m", self.model,
                "-f", audio_path,
                "--no-timestamps",
                "-np",          # no progress output
                "-l", self.language,
            ]
            if not self.gpu:
                cmd.append("--no-gpu")
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            logger.error("whisper.cpp timed out after %ds", timeout)
            return None
        if result.returncode != 0:
            logger.error("whisper.cpp failed (exit %d): %s",
                         result.returncode, result.stderr.strip())
            return None
        text = result.stdout.strip()
        return text if text else None
