# Whisper Transcription Hotkey Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** A Python daemon that listens for Scroll Lock (from USB HID MicrophoneController), records audio via PipeWire on keydown, transcribes via whisper.cpp (Vulkan/AMD 7900 XTX) on keyup, and types the result into the focused window via ydotool.

**Architecture:** evdev grabs the keyboard exclusively so Scroll Lock never reaches applications; pw-record streams audio to a temp WAV while the key is held; on release whisper.cpp is invoked as a subprocess with the Vulkan backend for GPU-accelerated transcription; ydotool injects the resulting text. A systemd user service provides autostart.

**Tech Stack:** Python 3.14, python-evdev, whisper.cpp (compiled with GGML_VULKAN=ON), pw-record (PipeWire), ydotool, notify-send, systemd user services

---

## Prerequisites

Before starting tasks, ensure these are available:

```bash
# Check tools
which pw-record ydotool notify-send
python3 -m pip show evdev 2>/dev/null || echo "evdev missing"
```

---

### Task 1: Install Python dependencies

**Files:**
- Create: `requirements.txt`

**Step 1: Create requirements file**

```
evdev>=1.6.0
```

Save to `/mnt/LargeNVMe/Projects/GitHub/AIIntegrations/requirements.txt`

**Step 2: Install**

```bash
pip install evdev
```

Expected: Successfully installed evdev

**Step 3: Install system tools**

```bash
sudo dnf install -y ydotool libnotify
```

Expected: ydotool and notify-send available

**Step 4: Verify**

```bash
python3 -c "import evdev; print(evdev.__version__)"
which ydotool notify-send pw-record
```

Expected: version printed, all paths shown

**Step 5: Commit**

```bash
cd /mnt/LargeNVMe/Projects/GitHub/AIIntegrations
git add requirements.txt
git commit -m "chore: add Python requirements"
```

---

### Task 2: Build whisper.cpp with Vulkan backend

**Files:**
- Create: `~/bin/whisper-main` (compiled binary)
- Create: `~/bin/models/` (directory for models)

**Step 1: Install Vulkan build dependencies**

```bash
sudo dnf install -y cmake gcc-c++ vulkan-devel glslc
```

**Step 2: Clone and build**

```bash
cd /tmp
git clone https://github.com/ggerganov/whisper.cpp
cd whisper.cpp
cmake -B build -DGGML_VULKAN=ON -DCMAKE_BUILD_TYPE=Release
cmake --build build --config Release -j$(nproc)
```

Expected: build completes with no errors; `build/bin/whisper-main` exists

**Step 3: Install binary**

```bash
mkdir -p ~/bin/models
cp /tmp/whisper.cpp/build/bin/whisper-main ~/bin/
chmod +x ~/bin/whisper-main
```

**Step 4: Download model**

```bash
cd /tmp/whisper.cpp
bash models/download-ggml-model.sh large-v3
cp models/ggml-large-v3.bin ~/bin/models/
```

Expected: `~/bin/models/ggml-large-v3.bin` exists (~3.1 GB)

**Step 5: Smoke test**

```bash
# Record 3 seconds of test audio
pw-record -r 16000 --channels 1 /tmp/test.wav &
sleep 3
kill %1
# Transcribe
~/bin/whisper-main -m ~/bin/models/ggml-large-v3.bin -f /tmp/test.wav --no-timestamps -np
```

Expected: transcription printed (even if silence, no crash)

---

### Task 3: Write the key detection module with tests

**Files:**
- Create: `src/whisper_hotkey/key_watcher.py`
- Create: `tests/test_key_watcher.py`

**Step 1: Create source directory**

```bash
mkdir -p /mnt/LargeNVMe/Projects/GitHub/AIIntegrations/src/whisper_hotkey
touch /mnt/LargeNVMe/Projects/GitHub/AIIntegrations/src/whisper_hotkey/__init__.py
mkdir -p /mnt/LargeNVMe/Projects/GitHub/AIIntegrations/tests
```

**Step 2: Write the failing test**

Create `tests/test_key_watcher.py`:

```python
"""Tests for key_watcher module."""
from unittest.mock import MagicMock, patch
from src.whisper_hotkey.key_watcher import find_keyboard_device, KeyWatcher


def test_find_keyboard_device_returns_none_when_no_devices():
    with patch("evdev.list_devices", return_value=[]):
        result = find_keyboard_device()
    assert result is None


def test_find_keyboard_device_finds_scroll_lock_capable():
    mock_dev = MagicMock()
    mock_dev.path = "/dev/input/event0"
    mock_dev.capabilities.return_value = {1: [70]}  # KEY_SCROLLLOCK = 70
    with patch("evdev.list_devices", return_value=["/dev/input/event0"]):
        with patch("evdev.InputDevice", return_value=mock_dev):
            result = find_keyboard_device()
    assert result == mock_dev


def test_key_watcher_calls_on_press_on_key_down():
    on_press = MagicMock()
    on_release = MagicMock()
    watcher = KeyWatcher(device=MagicMock(), keycode=70,
                         on_press=on_press, on_release=on_release)
    mock_event = MagicMock()
    mock_event.type = 1   # EV_KEY
    mock_event.code = 70  # KEY_SCROLLLOCK
    mock_event.value = 1  # key down
    watcher.handle_event(mock_event)
    on_press.assert_called_once()
    on_release.assert_not_called()


def test_key_watcher_calls_on_release_on_key_up():
    on_press = MagicMock()
    on_release = MagicMock()
    watcher = KeyWatcher(device=MagicMock(), keycode=70,
                         on_press=on_press, on_release=on_release)
    mock_event = MagicMock()
    mock_event.type = 1
    mock_event.code = 70
    mock_event.value = 0  # key up
    watcher.handle_event(mock_event)
    on_release.assert_called_once()
    on_press.assert_not_called()


def test_key_watcher_ignores_other_keys():
    on_press = MagicMock()
    on_release = MagicMock()
    watcher = KeyWatcher(device=MagicMock(), keycode=70,
                         on_press=on_press, on_release=on_release)
    mock_event = MagicMock()
    mock_event.type = 1
    mock_event.code = 30  # KEY_A, not our key
    mock_event.value = 1
    watcher.handle_event(mock_event)
    on_press.assert_not_called()
    on_release.assert_not_called()
```

**Step 3: Run to verify failure**

```bash
cd /mnt/LargeNVMe/Projects/GitHub/AIIntegrations
python3 -m pytest tests/test_key_watcher.py -v 2>&1 | head -20
```

Expected: ImportError or ModuleNotFoundError

**Step 4: Implement `key_watcher.py`**

Create `src/whisper_hotkey/key_watcher.py`:

```python
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
```

**Step 5: Run tests to verify pass**

```bash
python3 -m pytest tests/test_key_watcher.py -v
```

Expected: 5 tests pass

**Step 6: Commit**

```bash
git add src/ tests/test_key_watcher.py
git commit -m "feat: add key_watcher module with evdev device discovery"
```

---

### Task 4: Write the audio recorder module with tests

**Files:**
- Create: `src/whisper_hotkey/recorder.py`
- Create: `tests/test_recorder.py`

**Step 1: Write failing tests**

Create `tests/test_recorder.py`:

```python
"""Tests for recorder module."""
import time
from unittest.mock import MagicMock, patch, call
from src.whisper_hotkey.recorder import AudioRecorder


def test_recorder_starts_pw_record_on_start():
    with patch("subprocess.Popen") as mock_popen:
        mock_popen.return_value = MagicMock()
        rec = AudioRecorder(output_path="/tmp/test.wav", sample_rate=16000)
        rec.start()
    mock_popen.assert_called_once()
    args = mock_popen.call_args[0][0]
    assert "pw-record" in args
    assert "/tmp/test.wav" in args


def test_recorder_stop_kills_process():
    with patch("subprocess.Popen") as mock_popen:
        mock_proc = MagicMock()
        mock_popen.return_value = mock_proc
        rec = AudioRecorder(output_path="/tmp/test.wav")
        rec.start()
        rec.stop()
    mock_proc.terminate.assert_called_once()
    mock_proc.wait.assert_called_once()


def test_recorder_duration_is_short_when_quick():
    with patch("subprocess.Popen") as mock_popen:
        mock_popen.return_value = MagicMock()
        rec = AudioRecorder(output_path="/tmp/test.wav")
        rec.start()
        # Don't sleep — stop immediately
        duration = rec.stop()
    assert duration < 0.5


def test_recorder_not_started_stop_is_noop():
    rec = AudioRecorder(output_path="/tmp/test.wav")
    duration = rec.stop()  # Should not raise
    assert duration == 0.0
```

**Step 2: Run to verify failure**

```bash
python3 -m pytest tests/test_recorder.py -v 2>&1 | head -10
```

Expected: ImportError

**Step 3: Implement `recorder.py`**

Create `src/whisper_hotkey/recorder.py`:

```python
"""Audio recording via pw-record (PipeWire)."""
import subprocess
import time


class AudioRecorder:
    """Records audio to a WAV file using pw-record."""

    def __init__(self, output_path: str, sample_rate: int = 16000, channels: int = 1):
        self.output_path = output_path
        self.sample_rate = sample_rate
        self.channels = channels
        self._process = None
        self._start_time = None

    def start(self):
        """Start recording. Non-blocking."""
        self._process = subprocess.Popen([
            "pw-record",
            "--rate", str(self.sample_rate),
            "--channels", str(self.channels),
            self.output_path,
        ])
        self._start_time = time.monotonic()

    def stop(self) -> float:
        """Stop recording. Returns duration in seconds."""
        if self._process is None:
            return 0.0
        self._process.terminate()
        self._process.wait()
        duration = time.monotonic() - self._start_time
        self._process = None
        self._start_time = None
        return duration
```

**Step 4: Run tests**

```bash
python3 -m pytest tests/test_recorder.py -v
```

Expected: 4 tests pass

**Step 5: Commit**

```bash
git add src/whisper_hotkey/recorder.py tests/test_recorder.py
git commit -m "feat: add AudioRecorder using pw-record"
```

---

### Task 5: Write the transcriber module with tests

**Files:**
- Create: `src/whisper_hotkey/transcriber.py`
- Create: `tests/test_transcriber.py`

**Step 1: Write failing tests**

Create `tests/test_transcriber.py`:

```python
"""Tests for transcriber module."""
from unittest.mock import patch, MagicMock
from src.whisper_hotkey.transcriber import Transcriber


def test_transcriber_calls_whisper_with_correct_args():
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=" Hello world\n", stderr="")
        t = Transcriber(binary="~/bin/whisper-main", model="~/bin/models/ggml-large-v3.bin")
        result = t.transcribe("/tmp/test.wav")
    assert result == "Hello world"
    args = mock_run.call_args[0][0]
    assert "~/bin/whisper-main" in args or any("whisper" in a for a in args)
    assert "/tmp/test.wav" in args


def test_transcriber_returns_none_on_failure():
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="error")
        t = Transcriber(binary="~/bin/whisper-main", model="~/bin/models/ggml-large-v3.bin")
        result = t.transcribe("/tmp/test.wav")
    assert result is None


def test_transcriber_strips_whitespace():
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="  transcribed text  \n", stderr="")
        t = Transcriber(binary="~/bin/whisper-main", model="~/bin/models/ggml-large-v3.bin")
        result = t.transcribe("/tmp/test.wav")
    assert result == "transcribed text"


def test_transcriber_returns_none_on_empty_output():
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="   \n", stderr="")
        t = Transcriber(binary="~/bin/whisper-main", model="~/bin/models/ggml-large-v3.bin")
        result = t.transcribe("/tmp/test.wav")
    assert result is None
```

**Step 2: Run to verify failure**

```bash
python3 -m pytest tests/test_transcriber.py -v 2>&1 | head -10
```

**Step 3: Implement `transcriber.py`**

Create `src/whisper_hotkey/transcriber.py`:

```python
"""Transcription via whisper.cpp subprocess."""
import os
import subprocess


class Transcriber:
    """Wraps whisper.cpp binary for audio transcription."""

    def __init__(self, binary: str, model: str, language: str = "en"):
        self.binary = os.path.expanduser(binary)
        self.model = os.path.expanduser(model)
        self.language = language

    def transcribe(self, audio_path: str) -> str | None:
        """Transcribe audio file. Returns text or None on failure."""
        result = subprocess.run(
            [
                self.binary,
                "-m", self.model,
                "-f", audio_path,
                "--no-timestamps",
                "-np",          # no progress output
                "-l", self.language,
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return None
        text = result.stdout.strip()
        return text if text else None
```

**Step 4: Run tests**

```bash
python3 -m pytest tests/test_transcriber.py -v
```

Expected: 4 tests pass

**Step 5: Commit**

```bash
git add src/whisper_hotkey/transcriber.py tests/test_transcriber.py
git commit -m "feat: add Transcriber wrapping whisper.cpp subprocess"
```

---

### Task 6: Write the text output module with tests

**Files:**
- Create: `src/whisper_hotkey/typer.py`
- Create: `tests/test_typer.py`

**Step 1: Write failing tests**

Create `tests/test_typer.py`:

```python
"""Tests for typer module."""
from unittest.mock import patch, MagicMock
from src.whisper_hotkey.typer import type_text


def test_type_text_calls_ydotool():
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        type_text("hello world")
    mock_run.assert_called_once()
    args = mock_run.call_args[0][0]
    assert "ydotool" in args
    assert "hello world" in args


def test_type_text_returns_true_on_success():
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        result = type_text("hello")
    assert result is True


def test_type_text_returns_false_on_failure():
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1)
        result = type_text("hello")
    assert result is False
```

**Step 2: Run to verify failure**

```bash
python3 -m pytest tests/test_typer.py -v 2>&1 | head -10
```

**Step 3: Implement `typer.py`**

Create `src/whisper_hotkey/typer.py`:

```python
"""Injects text into the focused window via ydotool."""
import subprocess


def type_text(text: str) -> bool:
    """Type text into currently focused window. Returns True on success."""
    result = subprocess.run(
        ["ydotool", "type", "--", text],
        capture_output=True,
    )
    return result.returncode == 0
```

**Step 4: Run tests**

```bash
python3 -m pytest tests/test_typer.py -v
```

Expected: 3 tests pass

**Step 5: Run all tests so far**

```bash
python3 -m pytest tests/ -v
```

Expected: all 16 tests pass

**Step 6: Commit**

```bash
git add src/whisper_hotkey/typer.py tests/test_typer.py
git commit -m "feat: add type_text using ydotool"
```

---

### Task 7: Write the main daemon script

**Files:**
- Create: `src/whisper_hotkey/daemon.py`
- Create: `bin/whisper-transcribe` (entry point)

**Step 1: Create `daemon.py`**

Create `src/whisper_hotkey/daemon.py`:

```python
"""Main daemon: coordinates key watching, recording, transcription, and typing."""
import os
import signal
import subprocess
import sys
import threading

import evdev

from .key_watcher import KeyWatcher, find_keyboard_device
from .recorder import AudioRecorder
from .transcriber import Transcriber
from .typer import type_text

# Configuration — edit these to taste
MODEL_PATH   = os.path.expanduser("~/bin/models/ggml-large-v3.bin")
WHISPER_BIN  = os.path.expanduser("~/bin/whisper-main")
AUDIO_PATH   = "/tmp/whisper-in.wav"
HOTKEY       = evdev.ecodes.KEY_SCROLLLOCK
MIN_DURATION = 0.5   # seconds; shorter recordings discarded
LANGUAGE     = "en"

recorder    = AudioRecorder(output_path=AUDIO_PATH)
transcriber = Transcriber(binary=WHISPER_BIN, model=MODEL_PATH, language=LANGUAGE)


def notify(summary: str, body: str = "", urgency: str = "normal"):
    subprocess.Popen(
        ["notify-send", "-u", urgency, summary, body],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def on_press():
    recorder.start()
    notify("Whisper", "Recording…")


def on_release():
    duration = recorder.stop()
    notify("Whisper", "Transcribing…")
    if duration < MIN_DURATION:
        notify("Whisper", "Too short, discarded", urgency="low")
        return
    text = transcriber.transcribe(AUDIO_PATH)
    if text is None:
        notify("Whisper", "Transcription failed", urgency="critical")
        return
    if not type_text(text):
        notify("Whisper", "Failed to type text", urgency="critical")


def _cleanup(signum, frame):
    recorder.stop()
    sys.exit(0)


def main():
    signal.signal(signal.SIGTERM, _cleanup)
    signal.signal(signal.SIGINT, _cleanup)

    device = find_keyboard_device(HOTKEY)
    if device is None:
        print("Error: no keyboard device with Scroll Lock found.", file=sys.stderr)
        print("Check: python3 -c \"import evdev; [print(evdev.InputDevice(p).capabilities()) for p in evdev.list_devices()]\"", file=sys.stderr)
        sys.exit(1)

    print(f"Listening on {device.path} ({device.name})")
    watcher = KeyWatcher(device=device, keycode=HOTKEY,
                         on_press=on_press, on_release=on_release)
    watcher.run()


if __name__ == "__main__":
    main()
```

**Step 2: Create entry point**

Create `bin/whisper-transcribe`:

```python
#!/usr/bin/env python3
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from src.whisper_hotkey.daemon import main
main()
```

```bash
chmod +x /mnt/LargeNVMe/Projects/GitHub/AIIntegrations/bin/whisper-transcribe
```

**Step 3: Install entry point to ~/bin**

```bash
ln -sf /mnt/LargeNVMe/Projects/GitHub/AIIntegrations/bin/whisper-transcribe ~/bin/whisper-transcribe
```

**Step 4: Smoke test (dry run)**

```bash
# Verify imports work before running as daemon
cd /mnt/LargeNVMe/Projects/GitHub/AIIntegrations
python3 -c "from src.whisper_hotkey.daemon import notify, on_press, on_release; print('imports OK')"
```

Expected: `imports OK`

**Step 5: Commit**

```bash
git add src/whisper_hotkey/daemon.py bin/whisper-transcribe
git commit -m "feat: add main daemon script with signal handling"
```

---

### Task 8: Add systemd user service for autostart

**Files:**
- Create: `systemd/whisper-transcribe.service`
- Install to: `~/.config/systemd/user/`

**Step 1: Create service file**

Create `systemd/whisper-transcribe.service`:

```ini
[Unit]
Description=Whisper hotkey transcription daemon
After=graphical-session.target

[Service]
ExecStart=%h/bin/whisper-transcribe
Restart=on-failure
RestartSec=3

[Install]
WantedBy=graphical-session.target
```

**Step 2: Install and enable**

```bash
mkdir -p ~/.config/systemd/user
cp /mnt/LargeNVMe/Projects/GitHub/AIIntegrations/systemd/whisper-transcribe.service \
   ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now whisper-transcribe
```

**Step 3: Verify service is running**

```bash
systemctl --user status whisper-transcribe
journalctl --user -u whisper-transcribe -n 20
```

Expected: `Active: active (running)` and "Listening on /dev/input/eventX"

**Step 4: Commit**

```bash
git add systemd/whisper-transcribe.service
git commit -m "feat: add systemd user service for autostart"
```

---

### Task 9: End-to-end manual test

**No files — just verification.**

**Step 1: Restart daemon fresh**

```bash
systemctl --user restart whisper-transcribe
systemctl --user status whisper-transcribe
```

**Step 2: Open a text editor**

Open Kate, gedit, or any text field. Put cursor in it.

**Step 3: Hold Scroll Lock and speak**

Say clearly: "This is a test of the whisper transcription system."

Release Scroll Lock.

**Step 4: Verify**

- KDE notification "Recording…" appears while held
- "Transcribing…" notification appears on release
- Text appears in the text editor within ~3 seconds

**Step 5: Test accidental tap guard**

Tap Scroll Lock quickly (< 0.5s). Verify nothing is typed (silent discard).

**Step 6: Commit final notes**

```bash
git tag v1.0.0 -m "Working whisper transcription hotkey v1.0.0"
```

---

## Troubleshooting Reference

| Problem | Check |
|---------|-------|
| "no keyboard device found" | `python3 -c "import evdev; [print(p, evdev.InputDevice(p).name) for p in evdev.list_devices()]"` — find your HID device |
| ydotool fails | Ensure ydotoold daemon is running: `systemctl --user start ydotool` |
| whisper.cpp hangs | Test standalone: `~/bin/whisper-main -m ~/bin/models/ggml-large-v3.bin -f /tmp/whisper-in.wav` |
| Vulkan not used | Check whisper.cpp build: `~/bin/whisper-main --help 2>&1 \| grep -i vulkan` |
| Audio is silent | Check default source: `pactl info \| grep Source` |
