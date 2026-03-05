#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── Constants ────────────────────────────────────────────────────────────────
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
UNINSTALL=0
TARGET_USER=""

usage() {
    echo "Usage: sudo $0 USERNAME [--force-rebuild] [--uninstall]"
    echo ""
    echo "  USERNAME        The local user to set up whisper-transcribe for."
    echo "  --force-rebuild Re-clone and recompile whisper.cpp even if already built."
    echo "  --uninstall     Remove all installed components for USERNAME."
    exit 1
}

[[ $# -lt 1 ]] && usage

for arg in "$@"; do
    case "$arg" in
        --force-rebuild) FORCE_REBUILD=1 ;;
        --uninstall)     UNINSTALL=1 ;;
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
        glslc \
        ydotool \
        libnotify \
        pipewire-utils \
        python3-gobject \
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
        -DBUILD_SHARED_LIBS=OFF \
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
# ── Step 5: Download model ────────────────────────────────────────────────────
step_download_model() {
    if [[ -f "$MODEL_FILE" ]]; then
        skip "Model already present at $MODEL_FILE"
        return
    fi

    # whisper.cpp must be cloned (done in build step or may already exist)
    local script="$BUILD_TMP/models/download-ggml-model.sh"
    if [[ ! -f "$script" ]]; then
        info "Cloning whisper.cpp for model download helper..."
        rm -rf "$BUILD_TMP"
        git clone --depth 1 https://github.com/ggerganov/whisper.cpp "$BUILD_TMP"
    fi

    mkdir -p "$MODEL_DIR"
    info "Downloading ggml-large-v3.bin (~3.1 GB)..."
    bash "$script" large-v3
    [[ -f "$BUILD_TMP/models/ggml-large-v3.bin" ]] \
        || error "Download failed: $BUILD_TMP/models/ggml-large-v3.bin not found"
    install -m 644 "$BUILD_TMP/models/ggml-large-v3.bin" "$MODEL_FILE"
    done_ "Model installed to $MODEL_FILE"
}
# ── Step 6: Install Python package ───────────────────────────────────────────
step_install_entry_point() {
    info "Installing whisper-transcribe Python package..."
    pip3 install --prefix=/usr/local --break-system-packages "$SCRIPT_DIR"
    done_ "Package installed; entry point at $WHISPER_ENTRY"
}
# ── Step 7: Input group ───────────────────────────────────────────────────────
step_input_group() {
    if id -nG "$TARGET_USER" | grep -qw input; then
        skip "$TARGET_USER is already in the 'input' group."
    else
        info "Adding $TARGET_USER to 'input' group..."
        usermod -aG input "$TARGET_USER"
        done_ "$TARGET_USER added to 'input' group."
    fi
}

# ── Step 8: systemd user service ──────────────────────────────────────────────
step_systemd_service() {
    local service_dir
    service_dir="$(getent passwd "$TARGET_USER" | cut -d: -f6)/.config/systemd/user"
    local service_file="$service_dir/whisper-transcribe.service"

    info "Installing systemd user service for $TARGET_USER ..."
    mkdir -p "$service_dir"
    chown -R "$TARGET_USER:$TARGET_USER" "$(getent passwd "$TARGET_USER" | cut -d: -f6)/.config"

    cat > "$service_file" <<EOF
[Unit]
Description=Whisper hotkey transcription daemon
After=graphical-session.target ydotool.service
Requires=ydotool.service
StartLimitInterval=60
StartLimitBurst=3

[Service]
ExecStart=$WHISPER_ENTRY
Restart=on-failure
RestartSec=5
SyslogIdentifier=whisper-transcribe
TimeoutStopSec=5

[Install]
WantedBy=graphical-session.target
EOF
    chown "$TARGET_USER:$TARGET_USER" "$service_file"

    local ydotool_file="$service_dir/ydotool.service"
    cat > "$ydotool_file" <<'EOF'
[Unit]
Description=ydotoold input daemon
After=graphical-session.target

[Service]
ExecStart=/usr/bin/ydotoold
Restart=on-failure
RestartSec=3

[Install]
WantedBy=graphical-session.target
EOF
    chown "$TARGET_USER:$TARGET_USER" "$ydotool_file"

    # Enable via the user's running session bus if available, else leave a note
    local uid
    uid=$(id -u "$TARGET_USER")
    local xdg_runtime="/run/user/$uid"
    local bus_addr="unix:path=$xdg_runtime/bus"

    if [[ -S "$xdg_runtime/bus" ]]; then
        sudo -u "$TARGET_USER" \
            XDG_RUNTIME_DIR="$xdg_runtime" \
            DBUS_SESSION_BUS_ADDRESS="$bus_addr" \
            systemctl --user daemon-reload
        sudo -u "$TARGET_USER" \
            XDG_RUNTIME_DIR="$xdg_runtime" \
            DBUS_SESSION_BUS_ADDRESS="$bus_addr" \
            systemctl --user enable ydotool whisper-transcribe
        done_ "Services enabled for $TARGET_USER."
    else
        # User not logged in — enable via symlink manually
        local wants_dir="$service_dir/graphical-session.target.wants"
        mkdir -p "$wants_dir"
        ln -sf "$ydotool_file"   "$wants_dir/ydotool.service"
        ln -sf "$service_file"   "$wants_dir/whisper-transcribe.service"
        chown -R "$TARGET_USER:$TARGET_USER" "$wants_dir"
        done_ "Services installed for $TARGET_USER (will auto-enable on next login)."
    fi
}

# ── Step 9: Tray autostart ────────────────────────────────────────────────────
step_tray_autostart() {
    local home_dir
    home_dir="$(getent passwd "$TARGET_USER" | cut -d: -f6)"
    local autostart_dir="$home_dir/.config/autostart"
    local desktop_file="$autostart_dir/whisper-transcribe-tray.desktop"

    info "Installing tray autostart entry..."
    mkdir -p "$autostart_dir"
    cat > "$desktop_file" <<'EOF'
[Desktop Entry]
Type=Application
Name=Whisper Transcribe Tray
Exec=whisper-transcribe-tray
Icon=audio-input-microphone
Comment=System tray control for whisper-transcribe
X-KDE-autostart-phase=2
EOF
    chown "$TARGET_USER:$TARGET_USER" "$desktop_file"
    done_ "Tray autostart installed at $desktop_file"
}

# ── Step 10: Done ──────────────────────────────────────────────────────────────
step_done() {
    echo ""
    echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${GREEN}  Installation complete for: $TARGET_USER${NC}"
    echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""
    echo "  NOTE: Log out and back in for the 'input' group to take effect."
    echo ""
    echo "  To start now (from $TARGET_USER's graphical session):"
    echo "    systemctl --user start whisper-transcribe"
    echo ""
    echo "  To check logs:"
    echo "    journalctl --user -u whisper-transcribe -f"
    echo ""
    echo "  Hold Scroll Lock to record. Release to transcribe."
    echo ""
}

# ── Uninstall ─────────────────────────────────────────────────────────────────
step_uninstall() {
    local home_dir
    home_dir="$(getent passwd "$TARGET_USER" | cut -d: -f6)"
    local service_dir="$home_dir/.config/systemd/user"
    local uid
    uid=$(id -u "$TARGET_USER")
    local xdg_runtime="/run/user/$uid"
    local bus_addr="unix:path=$xdg_runtime/bus"

    info "Stopping and disabling services..."
    if [[ -S "$xdg_runtime/bus" ]]; then
        sudo -u "$TARGET_USER" \
            XDG_RUNTIME_DIR="$xdg_runtime" \
            DBUS_SESSION_BUS_ADDRESS="$bus_addr" \
            systemctl --user disable --now whisper-transcribe ydotool 2>/dev/null || true
        sudo -u "$TARGET_USER" \
            XDG_RUNTIME_DIR="$xdg_runtime" \
            DBUS_SESSION_BUS_ADDRESS="$bus_addr" \
            systemctl --user daemon-reload
    fi

    info "Removing service files..."
    rm -f  "$service_dir/whisper-transcribe.service"
    rm -f  "$service_dir/ydotool.service"
    rm -rf "$service_dir/whisper-transcribe.service.d"
    rm -f  "$service_dir/graphical-session.target.wants/whisper-transcribe.service"
    rm -f  "$service_dir/graphical-session.target.wants/ydotool.service"

    info "Uninstalling Python package..."
    pip3 uninstall --break-system-packages -y whisper-transcribe 2>/dev/null || true
    rm -f /usr/local/bin/whisper-transcribe /usr/local/bin/whisper-transcribe-tray

    info "Removing whisper-main binary..."
    rm -f "$WHISPER_BIN"

    info "Removing tray autostart..."
    rm -f "$(getent passwd "$TARGET_USER" | cut -d: -f6)/.config/autostart/whisper-transcribe-tray.desktop"

    echo ""
    echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${GREEN}  Uninstall complete for: $TARGET_USER${NC}"
    echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""
    echo "  The following were NOT removed (shared or large):"
    echo "    $MODEL_FILE  (~3.1 GB — delete manually if no longer needed)"
    echo "    $TARGET_USER's membership in the 'input' group"
    echo ""
}

# ── Entry point ───────────────────────────────────────────────────────────────
main() {
    if [[ $UNINSTALL -eq 1 ]]; then
        [[ $EUID -ne 0 ]] && error "Run as root: sudo $0 $TARGET_USER --uninstall"
        id "$TARGET_USER" &>/dev/null || error "User '$TARGET_USER' does not exist."
        step_uninstall
        return
    fi

    step_validate
    step_system_deps
    step_python_deps
    step_build_whisper
    step_download_model
    step_install_entry_point
    step_input_group
    step_systemd_service
    step_tray_autostart
    step_done
}

main
