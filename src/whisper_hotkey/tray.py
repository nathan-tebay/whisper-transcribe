"""System tray icon for whisper-transcribe control."""
import os
import subprocess

import dbus
import dbus.service
import dbus.mainloop.glib

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import GLib, Gtk

SERVICE    = "whisper-transcribe.service"
DROPIN_DIR = os.path.expanduser("~/.config/systemd/user/whisper-transcribe.service.d")

ICON_RUNNING = "audio-input-microphone"
ICON_STOPPED = "audio-input-microphone-muted"

SNI_IFACE   = "org.kde.StatusNotifierItem"
SNI_PATH    = "/StatusNotifierItem"
MENU_IFACE  = "com.canonical.dbusmenu"
MENU_PATH   = "/StatusNotifierMenu"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _systemctl(*args) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["systemctl", "--user", *args],
        capture_output=True, text=True,
    )


def _is_running() -> bool:
    return _systemctl("is-active", SERVICE).stdout.strip() == "active"


def _read_dropin(filename: str) -> dict[str, str]:
    path = os.path.join(DROPIN_DIR, filename)
    result = {}
    try:
        with open(path) as f:
            for line in f:
                line = line.strip().strip('"')
                if line.startswith("Environment="):
                    val = line[len("Environment="):].strip('"')
                    if "=" in val:
                        k, v = val.split("=", 1)
                        result[k] = v
    except FileNotFoundError:
        pass
    return result


def _write_dropin(filename: str, env_vars: dict[str, str]):
    os.makedirs(DROPIN_DIR, exist_ok=True)
    with open(os.path.join(DROPIN_DIR, filename), "w") as f:
        f.write("[Service]\n")
        for k, v in env_vars.items():
            f.write(f'Environment="{k}={v}"\n')


def _list_keyboards():
    import evdev
    keyboards = []
    for path in evdev.list_devices():
        try:
            dev = evdev.InputDevice(path)
            if evdev.ecodes.EV_KEY in dev.capabilities():
                keyboards.append((path, dev.name))
            dev.close()
        except (PermissionError, OSError):
            continue
    return keyboards


# ── Settings dialog ───────────────────────────────────────────────────────────

class SettingsDialog(Gtk.Dialog):
    def __init__(self):
        super().__init__(title="Whisper Transcribe — Settings")
        self.set_default_size(420, -1)
        self.add_buttons(
            Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
            Gtk.STOCK_OK,     Gtk.ResponseType.OK,
        )

        grid = Gtk.Grid(column_spacing=12, row_spacing=8, margin=12)
        self.get_content_area().add(grid)

        # Keyboard
        grid.attach(Gtk.Label(label="Keyboard:", halign=Gtk.Align.END), 0, 0, 1, 1)
        self._keyboard_combo = Gtk.ComboBoxText()
        keyboards = _list_keyboards()
        current_kb = _read_dropin("keyboard.conf").get("WHISPER_KEYBOARD", "")
        selected_idx = 0
        for i, (path, name) in enumerate(keyboards):
            self._keyboard_combo.append(name, f"{name}  ({path})")
            if current_kb and (current_kb.lower() in name.lower()
                               or name.lower() in current_kb.lower()):
                selected_idx = i
        self._keyboard_combo.set_active(selected_idx)
        grid.attach(self._keyboard_combo, 1, 0, 1, 1)

        # Backend
        grid.attach(Gtk.Label(label="Command backend:", halign=Gtk.Align.END), 0, 1, 1, 1)
        self._backend_combo = Gtk.ComboBoxText()
        for b in ["ollama", "claude"]:
            self._backend_combo.append(b, b)
        backend_settings = _read_dropin("backend.conf")
        current_backend = backend_settings.get("WHISPER_COMMAND_BACKEND", "ollama")
        self._backend_combo.set_active_id(current_backend)
        self._backend_combo.connect("changed", self._on_backend_changed)
        grid.attach(self._backend_combo, 1, 1, 1, 1)

        # Ollama model
        self._model_label = Gtk.Label(label="Ollama model:", halign=Gtk.Align.END)
        grid.attach(self._model_label, 0, 2, 1, 1)
        current_model = backend_settings.get("WHISPER_OLLAMA_MODEL", "qwen2.5:7b")
        self._model_entry = Gtk.Entry(text=current_model)
        grid.attach(self._model_entry, 1, 2, 1, 1)

        self._on_backend_changed(self._backend_combo)
        self.show_all()

    def _on_backend_changed(self, combo):
        visible = combo.get_active_id() == "ollama"
        self._model_label.set_visible(visible)
        self._model_entry.set_visible(visible)

    def apply(self):
        kb_id = self._keyboard_combo.get_active_id()
        if kb_id:
            _write_dropin("keyboard.conf", {"WHISPER_KEYBOARD": kb_id})

        backend = self._backend_combo.get_active_id() or "ollama"
        env: dict[str, str] = {"WHISPER_COMMAND_BACKEND": backend}
        if backend == "ollama":
            env["WHISPER_OLLAMA_MODEL"] = self._model_entry.get_text().strip()
        _write_dropin("backend.conf", env)

        _systemctl("daemon-reload")
        _systemctl("restart", SERVICE)


# ── DBusMenu — native menu protocol on the same D-Bus connection ──────────────

class DBusMenu(dbus.service.Object):
    """Implements com.canonical.dbusmenu on the same connection as the SNI."""

    _ID_STATUS   = 1
    _ID_SEP1     = 2
    _ID_TOGGLE   = 3
    _ID_SEP2     = 4
    _ID_SETTINGS = 5
    _ID_SEP3     = 6
    _ID_QUIT     = 7

    def __init__(self, bus_name, tray: "WhisperTray"):
        super().__init__(bus_name, MENU_PATH)
        self._tray = tray
        self._revision = 1

    def _menu_items(self):
        running = self._tray.running
        return [
            (self._ID_STATUS,   {"label": "🟢 Running" if running else "🔴 Stopped",
                                 "enabled": False}),
            (self._ID_SEP1,     {"type": "separator"}),
            (self._ID_TOGGLE,   {"label": "Stop" if running else "Start",
                                 "enabled": True}),
            (self._ID_SEP2,     {"type": "separator"}),
            (self._ID_SETTINGS, {"label": "Settings…", "enabled": True}),
            (self._ID_SEP3,     {"type": "separator"}),
            (self._ID_QUIT,     {"label": "Quit", "enabled": True}),
        ]

    @staticmethod
    def _encode_props(props: dict) -> dbus.Dictionary:
        out = {}
        for k, v in props.items():
            if isinstance(v, bool):
                out[k] = dbus.Boolean(v, variant_level=1)
            else:
                out[k] = dbus.String(str(v), variant_level=1)
        return dbus.Dictionary(out, signature="sv")

    def _make_node(self, item_id: int, props: dict) -> dbus.Struct:
        return dbus.Struct(
            (dbus.Int32(item_id),
             self._encode_props(props),
             dbus.Array([], signature="v")),
            signature="ia{sv}av",
            variant_level=1,
        )

    # ── com.canonical.dbusmenu methods ────────────────────────────────────────

    @dbus.service.method(MENU_IFACE, in_signature="iias", out_signature="u(ia{sv}av)")
    def GetLayout(self, parentId, recursionDepth, propertyNames):
        children = dbus.Array(
            [self._make_node(i, p) for i, p in self._menu_items()],
            signature="v",
        )
        root = dbus.Struct(
            (dbus.Int32(0), dbus.Dictionary({}, signature="sv"), children),
            signature="ia{sv}av",
        )
        return dbus.UInt32(self._revision), root

    @dbus.service.method(MENU_IFACE, in_signature="aias", out_signature="a(ia{sv})")
    def GetGroupProperties(self, ids, propertyNames):
        items = dict(self._menu_items())
        return dbus.Array(
            [(dbus.Int32(i), self._encode_props(items[i]))
             for i in ids if i in items],
            signature="(ia{sv})",
        )

    @dbus.service.method(MENU_IFACE, in_signature="is", out_signature="v")
    def GetProperty(self, item_id, name):
        items = dict(self._menu_items())
        if item_id in items and name in items[item_id]:
            return dbus.String(str(items[item_id][name]), variant_level=1)
        return dbus.String("", variant_level=1)

    @dbus.service.method(MENU_IFACE, in_signature="isvu", out_signature="")
    def Event(self, item_id, event_id, data, timestamp):
        if event_id != "clicked":
            return
        if item_id == self._ID_TOGGLE:
            GLib.idle_add(self._tray.toggle)
        elif item_id == self._ID_SETTINGS:
            GLib.idle_add(self._tray.open_settings)
        elif item_id == self._ID_QUIT:
            GLib.idle_add(Gtk.main_quit)

    @dbus.service.method(MENU_IFACE, in_signature="a(isvu)", out_signature="ai")
    def EventGroup(self, events):
        for item_id, event_id, data, timestamp in events:
            self.Event(item_id, event_id, data, timestamp)
        return dbus.Array([], signature="i")

    @dbus.service.method(MENU_IFACE, in_signature="i", out_signature="b")
    def AboutToShow(self, item_id):
        return dbus.Boolean(False)

    @dbus.service.method(MENU_IFACE, in_signature="ai", out_signature="aiai")
    def AboutToShowGroup(self, ids):
        return dbus.Array([], signature="i"), dbus.Array([], signature="i")

    @dbus.service.signal(MENU_IFACE, signature="a(ia{sv})a(ias)")
    def ItemsPropertiesUpdated(self, updated, removed):
        pass

    @dbus.service.signal(MENU_IFACE, signature="ui")
    def LayoutUpdated(self, revision, parent):
        pass

    @dbus.service.method("org.freedesktop.DBus.Properties",
                         in_signature="ss", out_signature="v")
    def Get(self, interface, prop):
        return self.GetAll(interface)[prop]

    @dbus.service.method("org.freedesktop.DBus.Properties",
                         in_signature="s", out_signature="a{sv}")
    def GetAll(self, interface):
        return dbus.Dictionary({
            "Version":       dbus.UInt32(3,       variant_level=1),
            "TextDirection": dbus.String("ltr",   variant_level=1),
            "Status":        dbus.String("normal", variant_level=1),
            "IconThemePath": dbus.Array([], signature="s", variant_level=1),
        }, signature="sv")

    def notify_layout_updated(self):
        self._revision += 1
        self.LayoutUpdated(dbus.UInt32(self._revision), dbus.Int32(0))


# ── StatusNotifierItem D-Bus service ─────────────────────────────────────────

class StatusNotifierItem(dbus.service.Object):
    def __init__(self, bus, tray: "WhisperTray"):
        self._tray = tray
        self._service_name = f"org.kde.StatusNotifierItem-{os.getpid()}-1"
        bus_name = dbus.service.BusName(self._service_name, bus=bus)
        super().__init__(bus_name, SNI_PATH)

        self._menu = DBusMenu(bus_name, tray)

        watcher = bus.get_object(
            "org.kde.StatusNotifierWatcher", "/StatusNotifierWatcher"
        )
        watcher.RegisterStatusNotifierItem(
            self._service_name,
            dbus_interface="org.kde.StatusNotifierWatcher",
        )

    @dbus.service.method("org.freedesktop.DBus.Properties",
                         in_signature="ss", out_signature="v")
    def Get(self, interface, prop):
        return self.GetAll(interface)[prop]

    @dbus.service.method("org.freedesktop.DBus.Properties",
                         in_signature="ssv", out_signature="")
    def Set(self, interface, prop, value):
        pass

    @dbus.service.method("org.freedesktop.DBus.Properties",
                         in_signature="s", out_signature="a{sv}")
    def GetAll(self, interface):
        running = self._tray.running
        return dbus.Dictionary({
            "Category":      dbus.String("ApplicationStatus",        variant_level=1),
            "Id":            dbus.String("whisper-transcribe",        variant_level=1),
            "Title":         dbus.String("Whisper Transcribe",        variant_level=1),
            "Status":        dbus.String("Active",                    variant_level=1),
            "IconName":      dbus.String(
                                 ICON_RUNNING if running else ICON_STOPPED,
                                 variant_level=1),
            "IconThemePath": dbus.String("",                          variant_level=1),
            "Menu":          dbus.ObjectPath(MENU_PATH,               variant_level=1),
            "ItemIsMenu":    dbus.Boolean(True,                       variant_level=1),
            "ToolTip":       dbus.Struct(
                                 ("", dbus.Array([], signature="(iiay)"),
                                  "Whisper Transcribe",
                                  "Running" if running else "Stopped"),
                                 signature="sa(iiay)ss",
                                 variant_level=1),
        }, signature="sv")

    @dbus.service.method(SNI_IFACE, in_signature="ii", out_signature="")
    def Activate(self, x, y):
        pass

    @dbus.service.method(SNI_IFACE, in_signature="ii", out_signature="")
    def ContextMenu(self, x, y):
        pass

    @dbus.service.method(SNI_IFACE, in_signature="ii", out_signature="")
    def SecondaryActivate(self, x, y):
        pass

    @dbus.service.method(SNI_IFACE, in_signature="is", out_signature="")
    def Scroll(self, delta, orientation):
        pass

    @dbus.service.signal(SNI_IFACE, signature="")
    def NewIcon(self):
        pass

    @dbus.service.signal(SNI_IFACE, signature="s")
    def NewStatus(self, status):
        pass

    def refresh(self):
        self._menu.notify_layout_updated()
        self.NewIcon()


# ── Tray controller ───────────────────────────────────────────────────────────

class WhisperTray:
    def __init__(self, bus):
        self.running = _is_running()
        self._sni = StatusNotifierItem(bus, self)
        GLib.timeout_add(2000, self._poll)

    def _poll(self) -> bool:
        was = self.running
        self.running = _is_running()
        if was != self.running:
            self._sni.refresh()
        return True

    def toggle(self):
        action = "stop" if self.running else "start"
        _systemctl(action, SERVICE)
        self.running = _is_running()
        self._sni.refresh()

    def open_settings(self):
        dialog = SettingsDialog()
        if dialog.run() == Gtk.ResponseType.OK:
            dialog.apply()
            self.running = _is_running()
            self._sni.refresh()
        dialog.destroy()


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    bus = dbus.SessionBus()
    WhisperTray(bus)
    Gtk.main()


if __name__ == "__main__":
    main()
