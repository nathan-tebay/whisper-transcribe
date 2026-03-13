# whisper-transcribe

A Linux desktop service for hotkey-triggered speech-to-text transcription using [whisper.cpp](https://github.com/ggerganov/whisper.cpp), with optional natural-language command mode powered by local or cloud-based LLMs.

Hold a hotkey to record audio, release to transcribe, and optionally interpret the result as a command to execute (launch apps, run shell commands, or send keystrokes).

## Features

- **Hotkey-triggered transcription**: Hold Scroll Lock (configurable) to record, release to transcribe
- **Command mode**: Hold Pause (configurable) to record and execute natural-language commands
  - Supports three response types: `GUI:` (launch apps), `TERMINAL:` (run commands in a terminal), `KEYS:` (send keystrokes via ydotool)
- **Multiple LLM backends**:
  - Local: Ollama (default), Claude CLI
  - Cloud: OpenAI, Groq, OpenRouter, LM Studio
- **Keyboard hotplug support**: Automatically detects newly connected keyboards
- **System tray icon**: GTK-based control panel with real-time settings
- **Configurable**: All settings in `~/.config/whisper-transcribe/config.json`

## Prerequisites

- **Linux desktop system** with evdev support (keyboards)
- **Python 3.9+**
- **System dependencies**:
  - `cmake`, `gcc-c++` (to build whisper.cpp)
  - `vulkan-devel`, `glslc` (for GPU acceleration)
  - `ydotool` (for keypress simulation)
  - `libnotify` (for desktop notifications)
  - `pipewire-utils` (for audio)
  - `python3-gobject` (for GTK/D-Bus tray icon)
  - `git` (to clone whisper.cpp)

- **Whisper model** (~3.1 GB): `ggml-large-v3.bin` auto-downloaded during install
- **LLM backend** (one of):
  - Ollama running on `localhost:11434` (default)
  - Claude CLI installed (`claude` must be in PATH)
  - OpenAI / Groq / OpenRouter API key
  - LM Studio running on `localhost:1234`

## Installation

### Quick Start

```bash
sudo ./install.sh YOUR_USERNAME
```

The install script will:
1. Install system dependencies (via dnf)
2. Build whisper.cpp with Vulkan GPU acceleration (~5–10 minutes)
3. Download the large-v3 model (~3.1 GB)
4. Install Python package and entry points to `/usr/local/bin`
5. Add your user to the `input` group (required for keyboard access)
6. Create systemd user service and tray autostart
7. Enable and start services (if logged in)

### Manual Steps After Install

**Log out and back in** for the `input` group membership to take effect. Then start the service:

```bash
systemctl --user start whisper-transcribe
```

To auto-start on next login (already done by install.sh if you were logged in):

```bash
systemctl --user enable whisper-transcribe ydotool
```

### Uninstall

```bash
sudo ./install.sh YOUR_USERNAME --uninstall
```

This removes services, the Python package, and the whisper binary. The model file (~3.1 GB) is kept; delete `/usr/local/share/whisper/models/ggml-large-v3.bin` manually if desired.

## Usage

### Basic Transcription

1. **Hold Scroll Lock** to start recording audio
2. **Release Scroll Lock** to stop and transcribe
3. The transcribed text is typed into your active window

### Command Mode

1. **Hold Pause** to start recording
2. **Release Pause** to stop recording
3. The audio is transcribed and sent to your configured LLM backend
4. The LLM interprets the command and returns one of:
   - `GUI: <command>` — launch an app or open a URL
   - `TERMINAL: <command>` — run a shell command in a terminal
   - `KEYS: <keycode-sequence>` — send keystrokes
5. The command is executed automatically

### Example Commands

**Voice input**: "open linkedin"
**LLM response**: `GUI: xdg-open https://www.linkedin.com`
**Result**: Browser opens LinkedIn

**Voice input**: "show disk usage"
**LLM response**: `TERMINAL: df -h`
**Result**: Terminal window opens with `df -h` running

**Voice input**: "select all"
**LLM response**: `KEYS: 29:1 30:1 30:0 29:0`
**Result**: Ctrl+A is sent to active window

### Check Status

```bash
journalctl --user -u whisper-transcribe -f
```

View real-time logs from the daemon.

## Configuration

Config file: `~/.config/whisper-transcribe/config.json`

Created on first run with sensible defaults. Edit directly or use the system tray icon.

### Common Settings (Tray UI)

| Key | Default | Notes |
|---|---|---|
| `hotkey` | `KEY_SCROLLLOCK` | Linux evdev code for transcription mode |
| `command_hotkey` | `KEY_PAUSE` | Linux evdev code for command mode |
| `language` | `en` | Whisper language code |
| `command_backend` | `ollama` | LLM backend: `ollama`, `claude`, `openai`, `groq`, `lmstudio`, `openrouter` |
| `min_duration` | `0.5` | Minimum audio duration (seconds) to transcribe |
| `run_command_prefix` | `command` | Unused (reserved for future use) |

### Ollama Settings

| Key | Default | Notes |
|---|---|---|
| `ollama_model` | `qwen2.5:7b` | Model name in Ollama |
| `ollama_url` | `http://localhost:11434/api/generate` | Ollama API endpoint |
| `ollama_timeout` | `30` | Request timeout (seconds) |

### OpenAI-Compatible Backends (OpenAI, Groq, OpenRouter, LM Studio)

| Key | Notes |
|---|---|
| `openai_compat_url` | Leave blank to use backend default; override to use custom endpoint |
| `openai_compat_api_key` | Bearer token (not needed for LM Studio) |
| `openai_compat_model` | Leave blank to use backend default; override to use different model |
| `openai_compat_timeout` | Request timeout (seconds) |

#### Backend Defaults

| Backend | URL | Default Model |
|---|---|---|
| `openai` | `https://api.openai.com/v1/chat/completions` | `gpt-4o-mini` |
| `groq` | `https://api.groq.com/openai/v1/chat/completions` | `llama-3.3-70b-versatile` |
| `lmstudio` | `http://localhost:1234/v1/chat/completions` | `local-model` |
| `openrouter` | `https://openrouter.ai/api/v1/chat/completions` | `openai/gpt-4o-mini` |

### Claude CLI Backend

| Key | Default | Notes |
|---|---|---|
| `claude_timeout` | `30` | Request timeout (seconds) |

Requires the `claude` CLI to be installed and accessible in PATH.

### Advanced Settings

| Key | Default | Notes |
|---|---|---|
| `whisper_binary` | `/usr/local/bin/whisper-main` | Path to whisper executable |
| `model_path` | `/usr/local/share/whisper/models/ggml-large-v3.bin` | Path to GGML model |
| `audio_path` | `/tmp/whisper-in.wav` | Temporary audio file (cleaned up automatically) |
| `terminal_command` | `konsole --new-tab -e bash -c` | Terminal emulator command (for TERMINAL: responses) |

## System Tray Icon

The tray icon (`whisper-transcribe-tray`) displays the current transcription status and provides quick access to settings.

**Main Settings Dialog** (`SettingsDialog`):
- Hotkey and command hotkey configuration
- LLM backend selector
- Model field (Ollama dropdown or OpenAI-compatible text entry, shown/hidden based on backend)

**Advanced Settings Dialog** (`AdvancedSettingsDialog`):
- All other configuration keys: timeouts, URLs, API keys, paths

Right-click or click the tray icon to open dialogs. Changes are saved to `config.json` immediately.

## Architecture

### Core Components

- **daemon** (`daemon.py`) — main service loop listening for hotkey events
- **key_watcher** (`key_watcher.py`) — evdev keyboard listener with hotplug support
- **recorder** (`recorder.py`) — audio capture to WAV
- **transcriber** (`transcriber.py`) — calls whisper-main binary
- **commander** (`commander.py`) — LLM-based command interpretation and execution
- **typer** (`typer.py`) — keypress simulation via ydotool
- **config** (`config.py`) — configuration loading/saving
- **tray** (`tray.py`) — GTK system tray UI with D-Bus SNI

### Command Execution Flow

1. User holds hotkey (e.g., Pause key)
2. Audio is recorded to a WAV file
3. Whisper transcribes the audio
4. Transcribed text is sent to the configured LLM backend
5. LLM responds with one of: `GUI: ...`, `TERMINAL: ...`, or `KEYS: ...`
6. Response is parsed and executed:
   - **GUI commands**: launched via `subprocess.Popen`
   - **TERMINAL commands**: run in the configured terminal emulator
   - **KEYS commands**: keystrokes sent via ydotool

## Environment Variables

Override config values at runtime:

```bash
WHISPER_COMMAND_BACKEND=claude whisper-transcribe
WHISPER_OLLAMA_MODEL=llama2 whisper-transcribe
```

## Troubleshooting

### Service won't start

Check logs:
```bash
journalctl --user -u whisper-transcribe -n 50
```

Common issues:
- User not in `input` group — run `sudo usermod -aG input $USER` and log back in
- ydotool not installed or running — verify `systemctl --user status ydotool`
- Whisper binary not found — verify `/usr/local/bin/whisper-main` exists and is executable

### Hotkeys not detected

- Verify the keyboard is listed in `/dev/input/` and readable by your user
- Check that your user is in the `input` group and has logged out/back in
- Verify hotkey codes in config (use `evtest` to find codes)

### Transcription very slow

- Check CPU/GPU usage: `nvidia-smi` or `glxinfo | grep "OpenGL"`
- Whisper may be falling back to CPU if GPU drivers aren't installed
- Reduce model size (use smaller Whisper model) if needed

### LLM command not executing

Check logs for the response format:
```bash
journalctl --user -u whisper-transcribe -f
```

The LLM must return exactly one line in the format:
```
GUI: command
TERMINAL: command
KEYS: keycode-sequence
```

If the LLM returns text without a prefix, the command won't execute. Adjust the LLM backend, model, or prompt.

## Development

Install in editable mode:
```bash
pip3 install --prefix=/usr/local -e /path/to/whisper-transcribe
```

Then reload the daemon:
```bash
systemctl --user restart whisper-transcribe
```

## License

TBD

## Contributing

Contributions welcome. Please ensure:
- Changes follow existing code style
- New config keys are added to `DEFAULTS` in `config.py`
- Tray UI is updated if new user-facing settings are added
