"""Main daemon: coordinates key watching, recording, transcription, and typing."""
import argparse
import logging
import os
import signal
import subprocess
import sys

import evdev

from .key_watcher import KeyWatcher, find_keyboard_device
from .recorder import AudioRecorder
from .transcriber import Transcriber
from .typer import type_text
from .commander import run_command

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

# Configuration — edit these to taste
MODEL_PATH   = "/usr/local/share/whisper/models/ggml-large-v3.bin"
WHISPER_BIN  = "/usr/local/bin/whisper-main"
AUDIO_PATH   = "/tmp/whisper-in.wav"
HOTKEY                  = evdev.ecodes.KEY_SCROLLLOCK
DEFAULT_KEYBOARD_FILTER = "Arduino"
MIN_DURATION = 0.5   # seconds; shorter recordings discarded
RUN_COMMAND_PREFIX = "run command"
LANGUAGE     = "en"

recorder    = AudioRecorder(output_path=AUDIO_PATH)
transcriber = Transcriber(binary=WHISPER_BIN, model=MODEL_PATH, language=LANGUAGE)


def notify(summary: str, body: str = "", urgency: str = "normal"):
    subprocess.Popen(
        ["notify-send", "-u", urgency, summary, body],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def on_press():
    logger.info("Recording started")
    recorder.start()
    notify("Whisper", "Recording…")


def on_release():
    duration = recorder.stop()
    logger.info("Recording stopped (%.2fs)", duration)
    if duration < MIN_DURATION:
        logger.info("Too short (%.2fs < %.2fs), discarded", duration, MIN_DURATION)
        notify("Whisper", "Too short, discarded", urgency="low")
        return
    notify("Whisper", "Transcribing…")
    text = transcriber.transcribe(AUDIO_PATH)
    if text is None:
        logger.error("Transcription failed")
        notify("Whisper", "Transcription failed", urgency="critical")
        return
    logger.info("Transcribed: %r", text)
    if text.lower().startswith(RUN_COMMAND_PREFIX + " "):
        natural = text[len(RUN_COMMAND_PREFIX):].strip()
        logger.info("Run-command trigger: %r", natural)
        notify("Whisper", f"Running: {natural}…")
        if not run_command(natural):
            notify("Whisper", "Command failed", urgency="critical")
        return

    if not type_text(text):
        logger.error("Failed to type text")
        notify("Whisper", "Failed to type text", urgency="critical")


def _cleanup(signum, frame):
    logger.info("Shutting down (signal %d)", signum)
    try:
        recorder.stop()
    except Exception as e:
        logger.error("Error stopping recorder during cleanup: %s", e)
    sys.exit(0)


def main():
    parser = argparse.ArgumentParser(description="Whisper hotkey transcription daemon")
    parser.add_argument(
        "-k", "--keyboard",
        default=os.environ.get("WHISPER_KEYBOARD", DEFAULT_KEYBOARD_FILTER),
        help="Device name filter (substring match, case-insensitive). "
             "Overrides WHISPER_KEYBOARD env var. Default: %(default)r",
    )
    args = parser.parse_args()

    signal.signal(signal.SIGTERM, _cleanup)
    signal.signal(signal.SIGINT, _cleanup)

    device = find_keyboard_device(HOTKEY, name_filter=args.keyboard)
    if device is None:
        logger.error("No keyboard device with Scroll Lock found.")
        logger.error(
            "Debug: python3 -c \"import evdev; "
            "[print(p, evdev.InputDevice(p).name) for p in evdev.list_devices()]\""
        )
        sys.exit(1)

    logger.info("Listening on %s (%s)", device.path, device.name)
    watcher = KeyWatcher(device=device, keycode=HOTKEY,
                         on_press=on_press, on_release=on_release)
    watcher.run()


if __name__ == "__main__":
    main()
