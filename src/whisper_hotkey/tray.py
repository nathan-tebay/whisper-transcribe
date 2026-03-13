"""System tray icon for whisper-transcribe control."""
import json
import os
import subprocess
import urllib.request
from urllib.parse import urlparse, urlunparse

import dbus
import dbus.service
import dbus.mainloop.glib

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import GLib, Gtk

from . import config as _config

SERVICE = "whisper-transcribe.service"

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



def _get_ollama_models(generate_url: str) -> list[str]:
    """Query the local Ollama instance for downloaded model names."""
    try:
        parts = urlparse(generate_url)
        tags_url = urlunparse(parts._replace(path="/api/tags"))
        with urllib.request.urlopen(tags_url, timeout=3) as resp:
            data = json.loads(resp.read())
        return sorted(m["name"] for m in data.get("models", []))
    except Exception:
        return []


def _hardware_keycode_to_evdev_name(hardware_keycode: int) -> str | None:
    """Convert a GTK hardware_keycode (XKB) to an evdev KEY_* name."""
    import evdev.ecodes as ec
    evdev_code = hardware_keycode - 8
    name = ec.KEY.get(evdev_code)
    if name is None:
        return None
    return name if isinstance(name, str) else name[0]


# ── Hotkey capture button ─────────────────────────────────────────────────────

# evdev codes for modifier/lock keys to skip during capture
_MODIFIER_CODES = {29, 97, 42, 54, 56, 100, 125, 126, 58, 69, 70}

class HotkeyButton(Gtk.Button):
    """Displays a key name; clicking it captures the next non-modifier keypress."""

    def __init__(self, initial_key: str):
        super().__init__(label=initial_key)
        self._key = initial_key
        self._handler_id = None
        self.connect("clicked", self._on_clicked)

    def _on_clicked(self, *_):
        if self._handler_id is not None:
            return
        self.set_label("Press a key…")
        toplevel = self.get_toplevel()
        self._handler_id = toplevel.connect("key-press-event", self._on_key_press)

    def _on_key_press(self, widget, event):
        evdev_code = event.hardware_keycode - 8
        if evdev_code in _MODIFIER_CODES:
            return True
        name = _hardware_keycode_to_evdev_name(event.hardware_keycode)
        if name:
            self._key = name
        self.set_label(self._key)
        widget.disconnect(self._handler_id)
        self._handler_id = None
        return True

    @property
    def key(self) -> str:
        return self._key


# ── Advanced settings dialog ──────────────────────────────────────────────────

class AdvancedSettingsDialog(Gtk.Dialog):
    """Editor for less-frequently-changed config fields."""

    _FIELDS = [
        ("whisper_binary",        "Whisper binary:"),
        ("model_path",            "Model path:"),
        ("audio_path",            "Audio temp file:"),
        ("language",              "Language:"),
        ("run_command_prefix",    "Command prefix:"),
        ("terminal_command",      "Terminal command:"),
        ("ollama_url",            "Ollama URL:"),
        ("openai_compat_url",     "OpenAI-compat URL:"),
        ("openai_compat_api_key", "OpenAI-compat API key:"),
    ]
    _NUMERIC = [
        ("min_duration",          "Min duration (s):",         0.1, 10.0, 0.1, 1),
        ("ollama_timeout",        "Ollama timeout (s):",        5,  300,  1,   0),
        ("claude_timeout",        "Claude timeout (s):",        5,  300,  1,   0),
        ("openai_compat_timeout", "OpenAI-compat timeout (s):", 5,  300,  1,   0),
    ]

    def __init__(self, parent, cfg: dict):
        super().__init__(title="Advanced Settings", transient_for=parent, modal=True)
        self.set_default_size(520, -1)
        self.add_buttons(
            Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
            Gtk.STOCK_OK,     Gtk.ResponseType.OK,
        )

        grid = Gtk.Grid(column_spacing=12, row_spacing=8, margin=12)
        self.get_content_area().add(grid)

        self._entries: dict[str, Gtk.Entry] = {}
        for row, (key, label) in enumerate(self._FIELDS):
            grid.attach(Gtk.Label(label=label, halign=Gtk.Align.END), 0, row, 1, 1)
            entry = Gtk.Entry(text=str(cfg.get(key, "")), hexpand=True)
            grid.attach(entry, 1, row, 1, 1)
            self._entries[key] = entry

        self._spins: dict[str, Gtk.SpinButton] = {}
        for i, (key, label, lo, hi, step, digits) in enumerate(self._NUMERIC):
            row = len(self._FIELDS) + i
            grid.attach(Gtk.Label(label=label, halign=Gtk.Align.END), 0, row, 1, 1)
            adj = Gtk.Adjustment(value=float(cfg.get(key, lo)),
                                 lower=lo, upper=hi, step_increment=step)
            spin = Gtk.SpinButton(adjustment=adj, digits=digits)
            grid.attach(spin, 1, row, 1, 1)
            self._spins[key] = spin

        self.show_all()

    def apply(self, cfg: dict):
        for key, entry in self._entries.items():
            cfg[key] = entry.get_text().strip()
        for key, _label, _lo, _hi, _step, digits in self._NUMERIC:
            spin = self._spins[key]
            cfg[key] = spin.get_value() if digits > 0 else int(spin.get_value())


# ── Settings dialog ───────────────────────────────────────────────────────────

class SettingsDialog(Gtk.Dialog):
    def __init__(self):
        super().__init__(title="Whisper Transcribe — Settings")
        self.set_default_size(460, -1)
        self.add_buttons(
            Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
            Gtk.STOCK_OK,     Gtk.ResponseType.OK,
        )

        grid = Gtk.Grid(column_spacing=12, row_spacing=8, margin=12)
        self.get_content_area().add(grid)

        cfg = _config.load()
        row = 0

        # Transcribe hotkey
        grid.attach(Gtk.Label(label="Transcribe hotkey:", halign=Gtk.Align.END), 0, row, 1, 1)
        self._hotkey_btn = HotkeyButton(cfg.get("hotkey", "KEY_SCROLLLOCK"))
        grid.attach(self._hotkey_btn, 1, row, 1, 1)
        row += 1

        # Command hotkey
        grid.attach(Gtk.Label(label="Command hotkey:", halign=Gtk.Align.END), 0, row, 1, 1)
        self._cmd_hotkey_btn = HotkeyButton(cfg.get("command_hotkey", "KEY_PAUSE"))
        grid.attach(self._cmd_hotkey_btn, 1, row, 1, 1)
        row += 1

        # Command backend
        grid.attach(Gtk.Label(label="Command backend:", halign=Gtk.Align.END), 0, row, 1, 1)
        self._backend_combo = Gtk.ComboBoxText()
        for b in ["ollama", "claude", "openai", "groq", "lmstudio", "openrouter"]:
            self._backend_combo.append(b, b)
        self._backend_combo.set_active_id(cfg.get("command_backend", "ollama"))
        self._backend_combo.connect("changed", self._on_backend_changed)
        grid.attach(self._backend_combo, 1, row, 1, 1)
        row += 1

        # Ollama model dropdown (shown only for ollama backend)
        self._ollama_model_label = Gtk.Label(label="Ollama model:", halign=Gtk.Align.END)
        grid.attach(self._ollama_model_label, 0, row, 1, 1)
        self._model_combo = Gtk.ComboBoxText.new_with_entry()
        current_model = cfg.get("ollama_model", "")
        models = _get_ollama_models(cfg.get("ollama_url", _config.DEFAULTS["ollama_url"]))
        if current_model and current_model not in models:
            models = [current_model] + models
        for m in models:
            self._model_combo.append_text(m)
        if current_model in models:
            self._model_combo.set_active(models.index(current_model))
        grid.attach(self._model_combo, 1, row, 1, 1)
        row += 1

        # OpenAI-compat model entry (shown for openai/groq/lmstudio/openrouter)
        self._oai_model_label = Gtk.Label(label="Model:", halign=Gtk.Align.END)
        grid.attach(self._oai_model_label, 0, row, 1, 1)
        self._oai_model_entry = Gtk.Entry(
            text=cfg.get("openai_compat_model", ""), hexpand=True,
            placeholder_text="e.g. gpt-4o-mini, llama-3.3-70b-versatile",
        )
        grid.attach(self._oai_model_entry, 1, row, 1, 1)
        row += 1

        # Advanced settings button
        adv_btn = Gtk.Button(label="Advanced settings…")
        adv_btn.connect("clicked", self._on_advanced)
        grid.attach(adv_btn, 1, row, 1, 1)

        self._on_backend_changed(self._backend_combo)
        self.show_all()

    _OAI_COMPAT_BACKENDS = {"openai", "groq", "lmstudio", "openrouter"}

    def _on_backend_changed(self, combo):
        backend = combo.get_active_id()
        is_ollama = backend == "ollama"
        is_oai    = backend in self._OAI_COMPAT_BACKENDS
        self._ollama_model_label.set_visible(is_ollama)
        self._model_combo.set_visible(is_ollama)
        self._oai_model_label.set_visible(is_oai)
        self._oai_model_entry.set_visible(is_oai)

    def _on_advanced(self, _):
        cfg = _config.load()
        dlg = AdvancedSettingsDialog(self, cfg)
        if dlg.run() == Gtk.ResponseType.OK:
            dlg.apply(cfg)
            _config.save(cfg)
        dlg.destroy()

    def apply(self):
        cfg = _config.load()

        cfg["hotkey"]         = self._hotkey_btn.key
        cfg["command_hotkey"] = self._cmd_hotkey_btn.key

        backend = self._backend_combo.get_active_id() or "ollama"
        cfg["command_backend"] = backend
        if backend == "ollama":
            model = self._model_combo.get_child().get_text().strip()
            if model:
                cfg["ollama_model"] = model
        elif backend in self._OAI_COMPAT_BACKENDS:
            cfg["openai_compat_model"] = self._oai_model_entry.get_text().strip()

        _config.save(cfg)
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
