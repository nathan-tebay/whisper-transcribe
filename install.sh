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

# ── Step 1: Validate ──────────────────────────────────────────────────────────
step_validate() {
    info "Validating environment..."

    [[ $EUID -ne 0 ]] && error "Run as root: sudo $0 $TARGET_USER"

    id "$TARGET_USER" &>/dev/null \
        || error "User '$TARGET_USER' does not exist."

    getent group input &>/dev/null \
        || error "'input' group does not exist. Is this a Linux desktop system?"

    done_ "Validation passed (user=$TARGET_USER)"
}

# ── Step 2: System dependencies ───────────────────────────────────────────────
step_system_deps() {
    info "Installing system dependencies via dnf..."
    dnf install -y \
        cmake \
        gcc-c++ \
        vulkan-devel \
        shaderc \
        ydotool \
        libnotify \
        pipewire-utils \
        git
    done_ "System dependencies installed."
}

# ── Step 3: Python dependencies ───────────────────────────────────────────────
step_python_deps() {
    # Running as root: pip3 installs to /usr/local/lib64/python3.x/site-packages/
    # which is system-wide and accessible to all users including TARGET_USER.
    if python3 -c "import evdev" &>/dev/null; then
        skip "python3-evdev already importable."
        return
    fi
    info "Installing python3-evdev..."
    pip3 install evdev
    done_ "python3-evdev installed."
}
# ── Step 4: Build whisper.cpp ─────────────────────────────────────────────────
step_build_whisper() {
    if [[ -x "$WHISPER_BIN" && $FORCE_REBUILD -eq 0 ]]; then
        skip "whisper-main already at $WHISPER_BIN (use --force-rebuild to rebuild)."
        return
    fi

    info "Cloning whisper.cpp into $BUILD_TMP ..."
    rm -rf "$BUILD_TMP"
    git clone --depth 1 https://github.com/ggerganov/whisper.cpp "$BUILD_TMP"

    info "Building with Vulkan backend (this takes 5-10 minutes)..."
    cmake -B "$BUILD_TMP/build" "$BUILD_TMP" \
        -DGGML_VULKAN=ON \
        -DCMAKE_BUILD_TYPE=Release
    cmake --build "$BUILD_TMP/build" --config Release -j"$(nproc)"

    local built_bin
    # whisper.cpp may produce whisper-main or whisper-cli depending on version
    built_bin=$(find "$BUILD_TMP/build/bin" -maxdepth 1 \
        \( -name "whisper-main" -o -name "whisper-cli" \) \
        -executable | head -1)

    [[ -z "$built_bin" ]] \
        && error "Build succeeded but no whisper binary found in $BUILD_TMP/build/bin/"

    install -m 755 "$built_bin" "$WHISPER_BIN"
    done_ "whisper-main installed to $WHISPER_BIN"
}
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
