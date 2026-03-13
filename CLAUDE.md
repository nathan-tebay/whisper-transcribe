# whisper-transcribe — Codebase Notes

## Architecture

- `src/whisper_hotkey/daemon.py` — main service loop; listens for hotkey events, triggers transcription or command mode
- `src/whisper_hotkey/recorder.py` — audio capture (WAV)
- `src/whisper_hotkey/transcriber.py` — calls whisper-main binary, returns text
- `src/whisper_hotkey/commander.py` — interprets transcribed text as a natural-language command via an LLM backend, then executes it
- `src/whisper_hotkey/typer.py` — types text / sends key sequences via ydotool
- `src/whisper_hotkey/config.py` — loads/saves `~/.config/whisper-transcribe/config.json`; defines all defaults
- `src/whisper_hotkey/tray.py` — system tray icon (D-Bus SNI + GTK); `SettingsDialog` + `AdvancedSettingsDialog`
- `src/whisper_hotkey/key_watcher.py` — evdev keyboard listener with hotplug support

## Command backends (`commander.py`)

`run_command()` routes to one of these based on `command_backend` config key:

| Backend value | Function | Notes |
|---|---|---|
| `ollama` | `ask_ollama()` | Default; calls local Ollama `/api/generate` |
| `claude` | `ask_claude()` | Calls `claude --print` subprocess (CLI must be installed) |
| `openai` | `ask_openai_compat()` | `https://api.openai.com/v1/chat/completions` |
| `groq` | `ask_openai_compat()` | `https://api.groq.com/openai/v1/chat/completions` |
| `lmstudio` | `ask_openai_compat()` | `http://localhost:1234/v1/chat/completions` |
| `openrouter` | `ask_openai_compat()` | `https://openrouter.ai/api/v1/chat/completions` |

All four OpenAI-compatible backends share `ask_openai_compat()`. Their URLs and default models are in `_OPENAI_COMPAT_URLS` / `_OPENAI_COMPAT_DEFAULT_MODELS` dicts. Adding a new compatible provider means adding entries to both dicts, `_OPENAI_COMPAT_BACKENDS`, and the tray combo list.

## Config keys (`config.py` DEFAULTS)

All keys must be present in `DEFAULTS`. Adding a new config key requires:
1. Add to `DEFAULTS` in `config.py`
2. Expose in tray: simple text/numeric fields go in `AdvancedSettingsDialog._FIELDS` / `_NUMERIC`; frequently-changed fields go in `SettingsDialog`

### OpenAI-compat specific keys
- `openai_compat_url` — override the built-in URL (leave blank to use backend default)
- `openai_compat_api_key` — Bearer token; not needed for LM Studio
- `openai_compat_model` — overrides the built-in default model for the selected backend
- `openai_compat_timeout` — seconds (default 30)

## Tray (`tray.py`)

- `SettingsDialog` — main dialog: hotkeys, backend selector, model field (ollama combo or openai-compat text entry shown/hidden by `_on_backend_changed`)
- `AdvancedSettingsDialog` — secondary dialog for less-frequent settings; purely driven by `_FIELDS` (text entries) and `_NUMERIC` (spin buttons)
- When adding a new OpenAI-compat backend: add to the `for b in [...]` loop in `SettingsDialog.__init__` and to `_OAI_COMPAT_BACKENDS`

## Install / deployment

- Install script: `install.sh` (requires root, takes USERNAME arg)
- Binaries go to `/usr/local/bin/`
- User systemd service: `~/.config/systemd/user/whisper-transcribe.service`
- Tray autostart: `~/.config/autostart/whisper-transcribe-tray.desktop`
