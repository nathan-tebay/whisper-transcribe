"""System tray icon for whisper-transcribe control."""
import os
import subprocess
import sys

import evdev
from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtGui import QColor, QIcon, QPainter, QPixmap
from PyQt6.QtWidgets import (
    QApplication, QComboBox, QDialog, QDialogButtonBox,
    QFormLayout, QLabel, QLineEdit, QMenu, QSystemTrayIcon,
)

SERVICE   = "whisper-transcribe.service"
DROPIN_DIR = os.path.expanduser("~/.config/systemd/user/whisper-transcribe.service.d")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _systemctl(*args) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["systemctl", "--user", *args],
        capture_output=True, text=True,
    )


def _is_running() -> bool:
    return _systemctl("is-active", SERVICE).stdout.strip() == "active"


def _make_icon(color: str) -> QIcon:
    px = QPixmap(22, 22)
    px.fill(Qt.GlobalColor.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QColor(color))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawEllipse(3, 3, 16, 16)
    p.end()
    return QIcon(px)


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


def _list_keyboards() -> list[tuple[str, str]]:
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

class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Whisper Transcribe — Settings")
        self.setMinimumWidth(380)

        layout = QFormLayout(self)
        layout.setSpacing(10)

        # Keyboard
        self._keyboard_combo = QComboBox()
        keyboards = _list_keyboards()
        current_kb = _read_dropin("keyboard.conf").get("WHISPER_KEYBOARD", "")
        selected_idx = 0
        for i, (path, name) in enumerate(keyboards):
            self._keyboard_combo.addItem(f"{name}  ({path})", name)
            if current_kb and (current_kb.lower() in name.lower()
                               or name.lower() in current_kb.lower()):
                selected_idx = i
        self._keyboard_combo.setCurrentIndex(selected_idx)
        layout.addRow("Keyboard:", self._keyboard_combo)

        # Backend
        self._backend_combo = QComboBox()
        self._backend_combo.addItems(["ollama", "claude"])
        backend_settings = _read_dropin("backend.conf")
        current_backend = backend_settings.get("WHISPER_COMMAND_BACKEND", "ollama")
        self._backend_combo.setCurrentText(current_backend)
        self._backend_combo.currentTextChanged.connect(self._on_backend_changed)
        layout.addRow("Command backend:", self._backend_combo)

        # Ollama model
        current_model = backend_settings.get("WHISPER_OLLAMA_MODEL", "qwen2.5:7b")
        self._model_edit = QLineEdit(current_model)
        self._model_label = QLabel("Ollama model:")
        layout.addRow(self._model_label, self._model_edit)
        self._on_backend_changed(current_backend)

        # Buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._apply)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def _on_backend_changed(self, backend: str):
        visible = backend == "ollama"
        self._model_label.setVisible(visible)
        self._model_edit.setVisible(visible)

    def _apply(self):
        kb_name = self._keyboard_combo.currentData()
        if kb_name:
            _write_dropin("keyboard.conf", {"WHISPER_KEYBOARD": kb_name})

        backend = self._backend_combo.currentText()
        env: dict[str, str] = {"WHISPER_COMMAND_BACKEND": backend}
        if backend == "ollama":
            env["WHISPER_OLLAMA_MODEL"] = self._model_edit.text().strip()
        _write_dropin("backend.conf", env)

        _systemctl("daemon-reload")
        _systemctl("restart", SERVICE)
        self.accept()


# ── Tray application ──────────────────────────────────────────────────────────

class WhisperTray:
    def __init__(self, app: QApplication):
        self.app = app
        self._icon_running = _make_icon("#4CAF50")  # green
        self._icon_stopped = _make_icon("#9E9E9E")  # grey

        self.tray = QSystemTrayIcon()
        self.tray.setToolTip("Whisper Transcribe")
        self.tray.activated.connect(self._on_activated)

        menu = QMenu()
        self._status_action = menu.addAction("")
        self._status_action.setEnabled(False)
        menu.addSeparator()
        self._toggle_action = menu.addAction("")
        self._toggle_action.triggered.connect(self._toggle)
        menu.addSeparator()
        menu.addAction("Settings…").triggered.connect(self._open_settings)
        menu.addSeparator()
        menu.addAction("Quit").triggered.connect(app.quit)
        self.tray.setContextMenu(menu)

        self._timer = QTimer()
        self._timer.timeout.connect(self._refresh)
        self._timer.start(2000)

        self._refresh()
        self.tray.show()

    def _refresh(self):
        running = _is_running()
        self.tray.setIcon(self._icon_running if running else self._icon_stopped)
        self._status_action.setText("● Running" if running else "○ Stopped")
        self._toggle_action.setText("Stop" if running else "Start")

    def _toggle(self):
        action = "stop" if _is_running() else "start"
        _systemctl(action, SERVICE)
        self._refresh()

    def _on_activated(self, reason):
        # Left-click toggles the service
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self._toggle()

    def _open_settings(self):
        SettingsDialog().exec()
        self._refresh()


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    WhisperTray(app)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
