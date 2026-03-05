"""Keyboard device discovery and event watching."""
import errno
import logging

import evdev
from evdev import ecodes

logger = logging.getLogger(__name__)


def find_keyboard_device(keycodes: list[int], name_filter: str = ""):
    """Return the first InputDevice that has any of the given keycodes, or None.

    If name_filter is set, only devices whose name contains that string
    (case-insensitive) are considered.
    """
    for path in evdev.list_devices():
        try:
            dev = evdev.InputDevice(path)
            if name_filter and name_filter.lower() not in dev.name.lower():
                dev.close()
                continue
            caps = dev.capabilities()
            device_keys = caps.get(ecodes.EV_KEY, [])
            if any(kc in device_keys for kc in keycodes):
                return dev
            dev.close()
        except (PermissionError, OSError):
            continue
    return None


class KeyWatcher:
    """Dispatches press/release callbacks for multiple keycodes on one device.

    callbacks: dict mapping keycode -> (on_press, on_release)
    """

    def __init__(self, device, callbacks: dict[int, tuple]):
        self.device = device
        self.callbacks = callbacks

    def handle_event(self, event):
        if event.type != ecodes.EV_KEY or event.code not in self.callbacks:
            return
        on_press, on_release = self.callbacks[event.code]
        if event.value == 1:    # key down (initial press only)
            on_press()
        elif event.value == 0:  # key up
            on_release()
        # value == 2 is autorepeat — intentionally ignored for hold-to-talk

    def run(self):
        """Block and process events. Exits cleanly if the device disconnects."""
        try:
            self.device.grab()
        except OSError as e:
            try:
                import subprocess
                pids = subprocess.check_output(
                    ["fuser", self.device.path], stderr=subprocess.DEVNULL
                ).decode().split()
                holders = ", ".join(pids)
            except Exception:
                holders = "unknown"
            raise OSError(
                f"Failed to grab {self.device.path}: device busy (held by PID {holders}). "
                "Stop any other whisper-transcribe instance first."
            ) from e

        try:
            for event in self.device.read_loop():
                self.handle_event(event)
        except OSError as e:
            if e.errno == errno.ENODEV:
                logger.error("Input device disconnected: %s", self.device.path)
            else:
                raise
        finally:
            try:
                self.device.ungrab()
            except OSError:
                pass  # device already gone
