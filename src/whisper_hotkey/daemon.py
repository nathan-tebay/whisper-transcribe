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
from .typer import type_text, press_return
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
RUN_COMMAND_PREFIX = "command"
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


def on_release():
    duration = recorder.stop()
    logger.info("Recording stopped (%.2fs)", duration)
    if duration < MIN_DURATION:
        logger.info("Too short (%.2fs < %.2fs), discarded", duration, MIN_DURATION)
        return
    text = transcriber.transcribe(AUDIO_PATH)
    if text is None:
        logger.error("Transcription failed")
        notify("Whisper", "Transcription failed", urgency="critical")
        return
    logger.info("Transcribed: %r", text)
    if text.lower().startswith(RUN_COMMAND_PREFIX):
        natural = text[len(RUN_COMMAND_PREFIX):].lstrip(' \t,.:;!?')
        logger.info("Run-command trigger: %r", natural)
        if not run_command(natural):
            notify("Whisper", "Command failed", urgency="critical")
        return

    # Strip trailing punctuation then check for "enter" suffix
    stripped = text.rstrip(' \t,.:;!?')
    if stripped.lower().endswith(" enter"):
        text = stripped[:-len(" enter")]
        send_return = True
    else:
        send_return = False

    if not type_text(text):
        logger.error("Failed to type text")
        notify("Whisper", "Failed to type text", urgency="critical")
        return

    if send_return:
        press_return()


_DROPIN_DIR  = os.path.expanduser("~/.config/systemd/user/whisper-transcribe.service.d")
_DROPIN_FILE = os.path.join(_DROPIN_DIR, "keyboard.conf")


def select_keyboard_interactively() -> str:
    """List keyboard-capable devices, prompt the user, return the chosen name."""
    keyboards = []
    for path in evdev.list_devices():
        try:
            dev = evdev.InputDevice(path)
            if evdev.ecodes.EV_KEY in dev.capabilities():
                keyboards.append((path, dev.name))
            dev.close()
        except (PermissionError, OSError):
            continue

    if not keyboards:
        print("No keyboard devices found.", file=sys.stderr)
        sys.exit(1)

    print("Available keyboards:")
    for i, (path, name) in enumerate(keyboards):
        print(f"  [{i}] {path}  {name}")

    while True:
        try:
            choice = input("Select keyboard [0]: ").strip()
            idx = int(choice) if choice else 0
            if 0 <= idx < len(keyboards):
                return keyboards[idx][1]
        except (ValueError, EOFError):
            pass
        print(f"Enter a number between 0 and {len(keyboards) - 1}.")


def _save_and_restart(keyboard_name: str):
    """Persist keyboard choice as a systemd drop-in and restart the service."""
    os.makedirs(_DROPIN_DIR, exist_ok=True)
    with open(_DROPIN_FILE, "w") as f:
        f.write(f'[Service]\nEnvironment="WHISPER_KEYBOARD={keyboard_name}"\n')
    print(f"Saved: WHISPER_KEYBOARD={keyboard_name!r}")

    import subprocess as _sp
    _sp.run(["systemctl", "--user", "daemon-reload"], check=True)
    _sp.run(["systemctl", "--user", "restart", "whisper-transcribe.service"], check=True)
    print("Service restarted.")


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
        nargs="?",
        const="__select__",
        default=os.environ.get("WHISPER_KEYBOARD", DEFAULT_KEYBOARD_FILTER),
        metavar="FILTER",
        help="Device name filter (substring match, case-insensitive). "
             "Omit the value to pick interactively. "
             "Overrides WHISPER_KEYBOARD env var. Default: %(default)r",
    )
    args = parser.parse_args()

    signal.signal(signal.SIGTERM, _cleanup)
    signal.signal(signal.SIGINT, _cleanup)

    if args.keyboard == "__select__":
        name = select_keyboard_interactively()
        _save_and_restart(name)
        sys.exit(0)
    else:
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
