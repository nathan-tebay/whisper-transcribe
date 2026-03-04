#!/usr/bin/env bash
set -euo pipefail

# ── Constants ────────────────────────────────────────────────────────────────
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WHISPER_BIN=/usr/local/bin/whisper-main
WHISPER_ENTRY=/usr/local/bin/whisper-transcribe
MODEL_DIR=/usr/local/share/whisper/models
MODEL_FILE="$MODEL_DIR/ggml-large-v3.bin"
BUILD_TMP=/tmp/whisper-cpp-build

# ── Colour helpers ────────────────────────────────────────────────────────────
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
skip()  { echo -e "${YELLOW}[SKIP]${NC}  $*"; }
done_() { echo -e "${GREEN}[DONE]${NC}  $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*" >&2; exit 1; }

# ── Argument parsing ──────────────────────────────────────────────────────────
FORCE_REBUILD=0
TARGET_USER=""

usage() {
    echo "Usage: sudo $0 USERNAME [--force-rebuild]"
    echo ""
    echo "  USERNAME        The local user to set up whisper-transcribe for."
    echo "  --force-rebuild Re-clone and recompile whisper.cpp even if already built."
    exit 1
}

[[ $# -lt 1 ]] && usage

for arg in "$@"; do
    case "$arg" in
        --force-rebuild) FORCE_REBUILD=1 ;;
        --help|-h)       usage ;;
        -*)              error "Unknown flag: $arg" ;;
        *)               TARGET_USER="$arg" ;;
    esac
done

[[ -z "$TARGET_USER" ]] && usage

# ── Steps (stubs — filled in by later tasks) ─────────────────────────────────
step_validate()          { true; }
step_system_deps()       { true; }
step_python_deps()       { true; }
step_build_whisper()     { true; }
step_download_model()    { true; }
step_install_entry_point() { true; }
step_input_group()       { true; }
step_systemd_service()   { true; }
step_done()              { true; }

# ── Entry point ───────────────────────────────────────────────────────────────
main() {
    step_validate
    step_system_deps
    step_python_deps
    step_build_whisper
    step_download_model
    step_install_entry_point
    step_input_group
    step_systemd_service
    step_done
}

main
