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
from . import config as _config

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

PUNCT = ' \t,.:;!?'


def notify(summary: str, body: str = "", urgency: str = "normal"):
    subprocess.Popen(
        ["notify-send", "-u", urgency, summary, body],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def _extract_command(text: str, prefix: str) -> str | None:
    """Return the natural-language portion if text starts with the command prefix.

    Requires a non-alpha character after the prefix to avoid matching words
    like 'commander'.
    """
    tl = text.lower()
    if not tl.startswith(prefix):
        return None
    rest = tl[len(prefix):]
    if rest and rest[0].isalpha():
        return None
    return text[len(prefix):].lstrip(PUNCT)


def _strip_enter_suffix(text: str) -> tuple[str, bool]:
    """Strip trailing 'enter' keyword. Returns (text, should_press_enter)."""
    stripped = text.rstrip(PUNCT)
    if stripped.lower() == "enter":
        return "", True
    if stripped.lower().endswith(" enter"):
        return stripped[:-len(" enter")], True
    return text, False


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


def _restart_service():
    subprocess.run(["systemctl", "--user", "restart", "whisper-transcribe.service"], check=True)
    print("Service restarted.")


def _save_and_restart(keyboard_name: str):
    """Persist keyboard choice to config.json and restart the service."""
    cfg = _config.load()
    cfg["keyboard_filter"] = keyboard_name
    _config.save(cfg)
    print(f"Saved: keyboard_filter={keyboard_name!r}")
    _restart_service()


def _select_backend_interactively() -> tuple[str, str | None]:
    """Prompt user to select backend and optionally an Ollama model."""
    cfg = _config.load()
    backends = ["ollama", "claude"]
    print("Available backends:")
    for i, b in enumerate(backends):
        print(f"  [{i}] {b}")
    while True:
        try:
            choice = input("Select backend [0]: ").strip()
            idx = int(choice) if choice else 0
            if 0 <= idx < len(backends):
                backend = backends[idx]
                break
        except (ValueError, EOFError):
            pass
        print("Enter 0 or 1.")

    model = None
    if backend == "ollama":
        default_model = cfg["ollama_model"]
        try:
            model = input(f"Ollama model [{default_model}]: ").strip() or default_model
        except EOFError:
            model = default_model

    return backend, model


def _save_backend_and_restart(backend: str, model: str | None):
    """Persist backend/model to config.json and restart the service."""
    cfg = _config.load()
    cfg["command_backend"] = backend
    if model:
        cfg["ollama_model"] = model
    _config.save(cfg)
    print(f"Saved: command_backend={backend!r}" + (f", ollama_model={model!r}" if model else ""))
    _restart_service()


def main():
    cfg = _config.load()

    parser = argparse.ArgumentParser(description="Whisper hotkey transcription daemon")
    parser.add_argument(
        "-k", "--keyboard",
        nargs="?",
        const="__select__",
        default=os.environ.get("WHISPER_KEYBOARD", cfg["keyboard_filter"]),
        metavar="FILTER",
        help="Device name filter (substring match, case-insensitive). "
             "Omit the value to pick interactively. "
             "Overrides WHISPER_KEYBOARD env var. Default: %(default)r",
    )
    parser.add_argument(
        "-b", "--backend",
        nargs="?",
        const="__select__",
        metavar="BACKEND",
        help="Command backend: 'ollama' or 'claude'. "
             "Omit the value to pick interactively. "
             "Overrides WHISPER_COMMAND_BACKEND env var.",
    )
    args = parser.parse_args()

    if args.keyboard == "__select__":
        name = select_keyboard_interactively()
        _save_and_restart(name)
        sys.exit(0)

    if args.backend is not None:
        if args.backend == "__select__":
            backend, model = _select_backend_interactively()
        else:
            backend = args.backend
            model = None
        _save_backend_and_restart(backend, model)
        sys.exit(0)

    hotkey     = getattr(evdev.ecodes, cfg["hotkey"])
    cmd_hotkey = getattr(evdev.ecodes, cfg["command_hotkey"])
    recorder    = AudioRecorder(output_path=cfg["audio_path"])
    transcriber = Transcriber(binary=cfg["whisper_binary"], model=cfg["model_path"],
                              language=cfg["language"])
    min_duration       = cfg["min_duration"]
    run_command_prefix = cfg["run_command_prefix"]
    _recording = False

    def on_press():
        nonlocal _recording
        if _recording:
            logger.warning("Button pressed while already recording, ignoring")
            return
        _recording = True
        logger.info("Recording started")
        recorder.start()

    def _stop_and_transcribe(label: str) -> str | None:
        """Stop recorder and transcribe. Returns text or None (already notifies on failure)."""
        nonlocal _recording
        if not _recording:
            return None
        _recording = False
        duration = recorder.stop()
        logger.info("%s recording stopped (%.2fs)", label, duration)
        if duration < min_duration:
            logger.info("Too short (%.2fs < %.2fs), discarded", duration, min_duration)
            return None
        text = transcriber.transcribe(cfg["audio_path"])
        if text is None:
            logger.error("Transcription failed")
            notify("Whisper", "Transcription failed", urgency="critical")
        return text

    def on_release():
        text = _stop_and_transcribe("Transcribe")
        if text is None:
            return
        logger.info("Transcribed: %r", text)

        natural = _extract_command(text, run_command_prefix)
        if natural is not None:
            logger.info("Command trigger: %r", natural)
            if not run_command(natural):
                notify("Whisper", "Command failed", urgency="critical")
            return

        text, send_return = _strip_enter_suffix(text)

        if text and not type_text(text):
            logger.error("Failed to type text")
            notify("Whisper", "Failed to type text", urgency="critical")
            return

        if send_return:
            press_return()

    def on_cmd_release():
        text = _stop_and_transcribe("Command")
        if text is None:
            return
        logger.info("Command transcribed: %r", text)

        # Strip the command prefix if present, otherwise use the full text
        natural = _extract_command(text, run_command_prefix) or text
        if not run_command(natural):
            notify("Whisper", "Command failed", urgency="critical")

    def _cleanup(signum, frame):
        logger.info("Shutting down (signal %d)", signum)
        try:
            recorder.stop()
        except Exception as e:
            logger.error("Error stopping recorder during cleanup: %s", e)
        sys.exit(0)

    signal.signal(signal.SIGTERM, _cleanup)
    signal.signal(signal.SIGINT, _cleanup)

    device = find_keyboard_device([hotkey, cmd_hotkey], name_filter=args.keyboard)
    if device is None:
        logger.error("No keyboard device found (filter=%r).", args.keyboard)
        logger.error(
            "Debug: python3 -c \"import evdev; "
            "[print(p, evdev.InputDevice(p).name) for p in evdev.list_devices()]\""
        )
        sys.exit(1)

    logger.info("Listening on %s (%s)", device.path, device.name)
    watcher = KeyWatcher(device=device, callbacks={
        hotkey:     (on_press, on_release),
        cmd_hotkey: (on_press, on_cmd_release),
    })
    watcher.run()


if __name__ == "__main__":
    main()
