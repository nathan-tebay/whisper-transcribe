"""Keyboard device discovery and hotplug-aware event watching."""
import errno
import logging
import threading

import evdev
from evdev import ecodes

logger = logging.getLogger(__name__)


def _event_num(path: str) -> int:
    return int(path.rsplit("event", 1)[-1])


def _sorted_devices() -> list[str]:
    """Return event device paths sorted by event number ascending.

    Lower event numbers are primary hardware interfaces; higher numbers are
    typically duplicate/virtual nodes for the same physical device.
    """
    return sorted(evdev.list_devices(), key=_event_num)


class MultiDeviceWatcher:
    """Watches all keyboard devices for hotkey events with hotplug support.

    Discovers devices whose names contain name_filter (default: "keyboard"),
    starts a thread for each, and rescans every poll_interval seconds so
    newly plugged-in devices are picked up automatically.  When a device is
    unplugged its thread exits and its slot becomes available again.

    Duplicate physical devices (same vendor/product/phys) are skipped so a
    single physical keyboard that exposes multiple event nodes doesn't fire
    callbacks twice.

    callbacks: dict mapping keycode -> (on_press, on_release)
    """

    def __init__(self, keycodes: list[int], callbacks: dict[int, tuple],
                 name_filter: str = "keyboard", poll_interval: float = 2.0):
        self._keycodes       = set(keycodes)
        self.callbacks       = callbacks
        self._name_filter    = name_filter.lower()
        self._poll_interval  = poll_interval
        self._threads: dict[str, threading.Thread] = {}  # path  -> thread
        self._seen_phys: set[str] = set()               # phys keys in use
        self._lock  = threading.Lock()
        self._stop  = threading.Event()

    def _phys_key(self, dev) -> str:
        info = dev.info
        phys = dev.phys or dev.name
        # Strip the interface suffix (e.g. "/input0") so all event nodes that
        # belong to the same physical USB device share one phys key.
        base_phys = phys.split("/input")[0] if "/input" in phys else phys
        return f"{info.vendor:04x}:{info.product:04x}:{base_phys}"

    def _try_open(self, path: str):
        """Open path if it qualifies; return open InputDevice or None."""
        try:
            dev = evdev.InputDevice(path)
            if self._name_filter not in dev.name.lower():
                dev.close()
                return None
            keys = dev.capabilities().get(ecodes.EV_KEY, [])
            if not any(kc in keys for kc in self._keycodes):
                dev.close()
                return None
            return dev
        except (PermissionError, OSError):
            return None

    def _watch(self, path: str, dev, phys_key: str):
        logger.info("Watching %s (%s)", path, dev.name)
        try:
            for event in dev.read_loop():
                if self._stop.is_set():
                    break
                if event.type != ecodes.EV_KEY or event.code not in self.callbacks:
                    continue
                on_press, on_release = self.callbacks[event.code]
                if event.value == 1:    # key down
                    on_press()
                elif event.value == 0:  # key up
                    on_release()
                # value == 2 is autorepeat — ignored for hold-to-talk
        except OSError as e:
            if e.errno == errno.ENODEV:
                logger.info("Device disconnected: %s", path)
            else:
                logger.error("Device error on %s: %s", path, e)
        finally:
            try:
                dev.close()
            except OSError:
                pass
            with self._lock:
                self._threads.pop(path, None)
                self._seen_phys.discard(phys_key)
            logger.info("Stopped watching %s", path)

    def _scan(self):
        for path in _sorted_devices():
            with self._lock:
                if path in self._threads:
                    continue
            dev = self._try_open(path)
            if dev is None:
                continue
            phys_key = self._phys_key(dev)
            with self._lock:
                if phys_key in self._seen_phys:
                    dev.close()
                    continue
                self._seen_phys.add(phys_key)
                t = threading.Thread(
                    target=self._watch, args=(path, dev, phys_key),
                    daemon=True, name=f"keywatcher-{path}",
                )
                self._threads[path] = t
            t.start()

    def run(self):
        """Block until stop() is called, scanning for new devices periodically."""
        self._scan()
        while not self._stop.wait(self._poll_interval):
            self._scan()

    def stop(self):
        self._stop.set()
