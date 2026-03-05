"""Keyboard device discovery and event watching."""
import evdev
from evdev import ecodes


def find_keyboard_device(keycode: int = ecodes.KEY_SCROLLLOCK, name_filter: str = ""):
    """Return the first InputDevice that has the given keycode, or None.

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
            if keycode in caps.get(ecodes.EV_KEY, []):
                return dev
            dev.close()  # close non-matching devices to avoid fd leaks
        except (PermissionError, OSError):
            continue
    return None


class KeyWatcher:
    """Calls on_press/on_release when a specific key is pressed/released."""

    def __init__(self, device, keycode: int, on_press, on_release):
        self.device = device
        self.keycode = keycode
        self.on_press = on_press
        self.on_release = on_release

    def handle_event(self, event):
        if event.type != ecodes.EV_KEY or event.code != self.keycode:
            return
        if event.value == 1:    # key down (initial press only)
            self.on_press()
        elif event.value == 0:  # key up
            self.on_release()
        # value == 2 is autorepeat — intentionally ignored for hold-to-talk

    def run(self):
        """Block and process events. Call from a thread."""
        try:
            self.device.grab()
        except OSError as e:
            raise OSError(f"Failed to grab device {self.device.path}: {e}") from e
        try:
            for event in self.device.read_loop():
                self.handle_event(event)
        finally:
            self.device.ungrab()
