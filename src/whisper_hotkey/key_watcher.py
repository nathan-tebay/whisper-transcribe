"""Keyboard device discovery and event watching."""
import evdev
from evdev import ecodes


def find_keyboard_device(keycode: int = ecodes.KEY_SCROLLLOCK):
    """Return the first InputDevice that has the given keycode, or None."""
    for path in evdev.list_devices():
        try:
            dev = evdev.InputDevice(path)
            caps = dev.capabilities()
            if keycode in caps.get(ecodes.EV_KEY, []):
                return dev
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
        if event.value == 1:    # key down
            self.on_press()
        elif event.value == 0:  # key up
            self.on_release()

    def run(self):
        """Block and process events. Call from a thread."""
        self.device.grab()
        try:
            for event in self.device.read_loop():
                self.handle_event(event)
        finally:
            self.device.ungrab()
