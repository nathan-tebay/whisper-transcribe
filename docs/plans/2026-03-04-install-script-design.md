# Design: install.sh

**Date:** 2026-03-04
**Status:** Approved

## Overview

A single self-contained bash script that installs the whisper hotkey transcription system system-wide for a named user on Fedora Linux.

## Usage

```bash
sudo ./install.sh USERNAME [--force-rebuild]
```

## Steps (in order)

| Step | Action | Skip condition |
|------|--------|----------------|
| 1 | Validate: root check, username exists, input group exists | Exits with error if fails |
| 2 | Install dnf deps: cmake gcc-c++ vulkan-devel shaderc ydotool libnotify pipewire-utils | dnf is idempotent |
| 3 | Install python3-evdev via pip | Skip if already importable |
| 4 | Clone + build whisper.cpp with `-DGGML_VULKAN=ON` | Skip if `/usr/local/bin/whisper-main` exists and no `--force-rebuild` |
| 5 | Download `ggml-large-v3.bin` via whisper.cpp helper script | Skip if `/usr/local/share/whisper/models/ggml-large-v3.bin` exists |
| 6 | Write `/usr/local/bin/whisper-transcribe` (Python wrapper with hardcoded project path) | Always overwrite |
| 7 | Add user to `input` group | Skip if already member |
| 8 | Write + enable systemd user service for USERNAME | Always overwrite service file |
| 9 | Print post-install instructions | — |

## Output Style

- Coloured prefixes: `[INFO]` (green), `[SKIP]` (yellow), `[DONE]` (green), `[ERROR]` (red)
- Each step announces itself before acting
- `set -euo pipefail` — exits immediately on any error

## Service File

Written inline by the script (not copied from `systemd/`), with `ExecStart=/usr/local/bin/whisper-transcribe` — correct for system-wide installs (the repo file still has `%h/bin/...` for development use).

## File Location

`/mnt/LargeNVMe/Projects/GitHub/AIIntegrations/install.sh`

## Post-Install Message

```
Installation complete for USERNAME.

NOTE: Log out and back in for the 'input' group to take effect.

To start now (from USERNAME's graphical session):
  systemctl --user start whisper-transcribe

To check logs:
  journalctl --user -u whisper-transcribe -f

Hold Scroll Lock to record. Release to transcribe.
```
