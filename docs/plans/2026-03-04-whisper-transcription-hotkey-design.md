# Design: Local Whisper Transcription with HID Hotkey

**Date:** 2026-03-04
**Status:** Approved

## Overview

A Python daemon listens for the Scroll Lock key emitted by an existing USB HID MicrophoneController (Arduino-based PTT device). On hold: records audio via PipeWire. On release: transcribes via whisper.cpp with Vulkan GPU acceleration on an AMD 7900 XTX, then types the result into the active window.

## Architecture

```
[USB HID MicrophoneController]
        │ Scroll Lock key events (hold-to-talk)
        ▼
[Python daemon: whisper-transcribe.py]
  - evdev: grabs keyboard device, watches KEY_SCROLLLOCK
  - key_down → spawn pw-record to /tmp/whisper-in.wav
  - key_up   → kill pw-record, invoke whisper.cpp
        │ WAV file
        ▼
[whisper.cpp subprocess]
  - Vulkan backend (--gpu vulkan or via GGML_VULKAN build flag)
  - model: ggml-large-v3.bin (~3 GB VRAM, ~2s for 30s audio on 7900 XTX)
  - outputs plain text to stdout
        │ transcription text
        ▼
[ydotool type]
  - types transcription into currently focused Wayland window
  - notify-send popup shown during recording
```

## Components

| Component | Tool | Notes |
|-----------|------|-------|
| Key detection | `python-evdev` | Exclusive grab; works on Wayland without X11 |
| Audio capture | `pw-record` (PipeWire) | Default mic; already installed on Fedora 43 |
| GPU inference | `whisper.cpp` + Vulkan | Build from source with `-DGGML_VULKAN=ON`; no ROCm needed |
| Text output | `ydotool` | Wayland-native key injection; xdotool fallback for X11 |
| Notifications | `notify-send` | KDE notification while recording is active |

## Data Flow

1. Daemon starts; scans `/dev/input/event*` for keyboard with Scroll Lock; grabs it exclusively
2. `KEY_SCROLLLOCK` pressed → spawn `pw-record -r 16000 --channels 1 /tmp/whisper-in.wav`; send `notify-send "Recording..."`
3. `KEY_SCROLLLOCK` released → send SIGTERM to `pw-record`; dismiss notification
4. If recording duration < 0.5s: discard silently (accidental tap guard)
5. Invoke `whisper-main -m ~/bin/models/ggml-large-v3.bin -f /tmp/whisper-in.wav --output-txt --no-timestamps -np`
6. Read stdout; strip whitespace
7. `ydotool type -- "<transcription>"`

## File Layout

```
~/bin/
  whisper-transcribe          # Python daemon (main script)
  whisper-main                # whisper.cpp compiled binary (symlinked)
  models/
    ggml-large-v3.bin         # Whisper large-v3 GGML model (~3.1 GB)
~/.config/systemd/user/
  whisper-transcribe.service  # autostart (optional)
```

## Build Notes

### whisper.cpp with Vulkan

```bash
git clone https://github.com/ggerganov/whisper.cpp
cd whisper.cpp
cmake -B build -DGGML_VULKAN=ON
cmake --build build --config Release -j$(nproc)
# Binary: build/bin/whisper-main
```

### Python dependencies

```
python-evdev   # pip install evdev
ydotool        # dnf install ydotool
notify-send    # dnf install libnotify (already present on KDE)
pw-record      # already installed (pipewire-utils)
```

### Model download

```bash
# Via whisper.cpp helper script:
bash models/download-ggml-model.sh large-v3
```

## Error Handling

| Scenario | Behavior |
|----------|----------|
| whisper.cpp non-zero exit | `notify-send` error toast; no text typed |
| Recording < 0.5s | Silent discard |
| ydotool unavailable | Log error; output to clipboard via `wl-copy` as fallback |
| SIGTERM/SIGINT | Kill any running `pw-record`; clean exit |

## Configuration (top of script)

```python
MODEL_PATH   = os.path.expanduser("~/bin/models/ggml-large-v3.bin")
WHISPER_BIN  = os.path.expanduser("~/bin/whisper-main")
HOTKEY       = evdev.ecodes.KEY_SCROLLLOCK
MIN_DURATION = 0.5   # seconds; shorter recordings discarded
LANGUAGE     = "en"  # or "" for auto-detect
```

## Optional: systemd autostart

```ini
# ~/.config/systemd/user/whisper-transcribe.service
[Unit]
Description=Whisper hotkey transcription daemon

[Service]
ExecStart=%h/bin/whisper-transcribe
Restart=on-failure

[Install]
WantedBy=default.target
```

Enable with: `systemctl --user enable --now whisper-transcribe`
