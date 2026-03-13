"""User configuration loaded from ~/.config/whisper-transcribe/config.json."""
import json
import os

CONFIG_PATH = os.path.expanduser("~/.config/whisper-transcribe/config.json")

DEFAULTS = {
    "whisper_binary": "/usr/local/bin/whisper-main",
    "model_path": "/usr/local/share/whisper/models/ggml-large-v3.bin",
    "audio_path": "/tmp/whisper-in.wav",
    "language": "en",
    "hotkey": "KEY_SCROLLLOCK",
    "command_hotkey": "KEY_PAUSE",
    "min_duration": 0.5,
    "run_command_prefix": "command",
    "command_backend": "ollama",
    "ollama_model": "qwen2.5:7b",
    "ollama_url": "http://localhost:11434/api/generate",
    "ollama_timeout": 30,
    "claude_timeout": 30,
    "openai_compat_url": "",
    "openai_compat_api_key": "",
    "openai_compat_model": "",
    "openai_compat_timeout": 30,
    "terminal_command": "konsole --new-tab -e bash -c",
}


def load() -> dict:
    """Load config from disk, filling missing keys with defaults."""
    cfg = dict(DEFAULTS)
    try:
        with open(CONFIG_PATH) as f:
            cfg.update(json.load(f))
    except FileNotFoundError:
        pass
    return cfg


def save(cfg: dict):
    """Write cfg to disk (only keys present in DEFAULTS are saved)."""
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    data = {k: cfg[k] for k in DEFAULTS if k in cfg}
    with open(CONFIG_PATH, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
