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
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*" >&2; }
done_() { echo -e "${GREEN}[DONE]${NC}  $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*" >&2; exit 1; }

# ── Distro detection ──────────────────────────────────────────────────────────
DISTRO_FAMILY=""

detect_distro() {
    [[ -f /etc/os-release ]] || error "Cannot detect distro: /etc/os-release not found."
    # shellcheck source=/dev/null
    . /etc/os-release
    case "${ID:-}" in
        fedora|rhel|centos|rocky|almalinux)
            DISTRO_FAMILY="fedora" ;;
        ubuntu|debian|linuxmint|pop)
            DISTRO_FAMILY="debian" ;;
        *)
            case "${ID_LIKE:-}" in
                *fedora*|*rhel*)   DISTRO_FAMILY="fedora" ;;
                *debian*|*ubuntu*) DISTRO_FAMILY="debian" ;;
                *) error "Unsupported distro '${ID:-unknown}'. Supported families: Fedora/RHEL, Debian/Ubuntu." ;;
            esac
            ;;
    esac
    info "Detected distro: ${PRETTY_NAME:-$ID} (family=$DISTRO_FAMILY)"
}

# ── GPU / build-backend detection ────────────────────────────────────────────
detect_build_backend() {
    # Already set via --build-backend flag — nothing to do.
    [[ -n "$BUILD_BACKEND" ]] && { info "Build backend: $BUILD_BACKEND (from --build-backend flag)"; return; }

    local -a options=("cpu")
    local -a labels=("CPU only (no GPU acceleration)")

    # NVIDIA — check for loaded driver or hardware presence
    if command -v nvidia-smi &>/dev/null || lspci 2>/dev/null | grep -qi nvidia; then
        options+=("cuda")
        labels+=("CUDA (NVIDIA GPU)")
    fi

    # Vulkan — check for installed ICDs (covers AMD, Intel, and NVIDIA with Vulkan drivers)
    if ls /usr/share/vulkan/icd.d/*.json /etc/vulkan/icd.d/*.json &>/dev/null 2>&1; then
        options+=("vulkan")
        labels+=("Vulkan (AMD / Intel / NVIDIA)")
    fi

    if [[ ${#options[@]} -eq 1 ]]; then
        BUILD_BACKEND="cpu"
        info "No GPU detected — using CPU backend."
        return
    fi

    echo ""
    info "GPU support detected. Select a build backend for whisper.cpp:"
    for i in "${!options[@]}"; do
        printf "    [%d] %s\n" "$i" "${labels[$i]}"
    done
    echo ""
    while true; do
        read -rp "    Backend [0]: " choice
        choice="${choice:-0}"
        if [[ "$choice" =~ ^[0-9]+$ ]] && (( choice < ${#options[@]} )); then
            BUILD_BACKEND="${options[$choice]}"
            break
        fi
        echo "    Enter a number between 0 and $(( ${#options[@]} - 1 ))."
    done
    info "Build backend: $BUILD_BACKEND"
}

# ── pip helper — handles --break-system-packages on Python 3.11+ ──────────────
_pip_install() {
    local flags="--prefix=/usr/local"
    pip3 install --help 2>&1 | grep -q -- "--break-system-packages" \
        && flags="$flags --break-system-packages"
    pip3 install $flags "$@"
}

# ── Argument parsing ──────────────────────────────────────────────────────────
FORCE_REBUILD=0
UNINSTALL=0
TARGET_USER=""
BUILD_BACKEND=""   # cpu | vulkan | cuda  (empty = auto-detect + prompt)

usage() {
    echo "Usage: sudo $0 USERNAME [OPTIONS]"
    echo ""
    echo "  USERNAME                    The local user to set up whisper-transcribe for."
    echo "  --build-backend=cpu|vulkan|cuda"
    echo "                              GPU backend for whisper.cpp. Skips the prompt."
    echo "  --force-rebuild             Re-clone and recompile whisper.cpp even if already built."
    echo "  --uninstall                 Remove all installed components for USERNAME."
    exit 1
}

[[ $# -lt 1 ]] && usage

for arg in "$@"; do
    case "$arg" in
        --force-rebuild)      FORCE_REBUILD=1 ;;
        --uninstall)          UNINSTALL=1 ;;
        --build-backend=*)    BUILD_BACKEND="${arg#*=}" ;;
        --help|-h)            usage ;;
        -*)                   error "Unknown flag: $arg" ;;
        *)                    TARGET_USER="$arg" ;;
    esac
done

[[ -z "$TARGET_USER" ]] && usage

if [[ -n "$BUILD_BACKEND" ]]; then
    case "$BUILD_BACKEND" in
        cpu|vulkan|cuda) ;;
        *) error "Invalid --build-backend='$BUILD_BACKEND'. Valid values: cpu, vulkan, cuda." ;;
    esac
fi

# ── Step 1: Validate ──────────────────────────────────────────────────────────
step_validate() {
    info "Validating environment..."

    [[ $EUID -ne 0 ]] && error "Run as root: sudo $0 $TARGET_USER"

    id "$TARGET_USER" &>/dev/null \
        || error "User '$TARGET_USER' does not exist."

    getent group input &>/dev/null \
        || error "'input' group does not exist. Is this a Linux desktop system?"

    detect_distro

    done_ "Validation passed (user=$TARGET_USER)"
}

# ── Step 2: System dependencies ───────────────────────────────────────────────

_PKGS_NEEDED=()   # packages to install this run
_CLEANUP_PKGS=()  # subset that are build-only and should be removed afterwards

# _need CHECK FEDORA_PKG DEBIAN_PKG
# Queues the distro-appropriate package if CHECK fails (i.e. not already present).
_need() {
    local check="$1"
    local pkg; pkg=$([[ "$DISTRO_FAMILY" = fedora ]] && echo "$2" || echo "$3")
    if eval "$check" &>/dev/null 2>&1; then
        skip "$pkg already present."
    else
        _PKGS_NEEDED+=("$pkg")
    fi
}

# _build_need CHECK FEDORA_PKG DEBIAN_PKG
# Like _need, but also schedules the package for removal after the build
# if we are the ones installing it (i.e. it wasn't present before).
_build_need() {
    local check="$1"
    local pkg; pkg=$([[ "$DISTRO_FAMILY" = fedora ]] && echo "$2" || echo "$3")
    if eval "$check" &>/dev/null 2>&1; then
        skip "$pkg already present."
    else
        _PKGS_NEEDED+=("$pkg")
        _CLEANUP_PKGS+=("$pkg")
    fi
}

# Check if a package name is available in the currently configured repositories.
_pkg_available() {
    local pkg="$1"
    case "$DISTRO_FAMILY" in
        fedora) dnf info "$pkg" &>/dev/null 2>&1 ;;
        debian) apt-cache show "$pkg" &>/dev/null 2>&1 ;;
    esac
}

# Enable Ubuntu's 'universe' repository if it is not already active.
# No-op on non-Ubuntu distros.
_ensure_universe_repo() {
    [[ "$DISTRO_FAMILY" != "debian" ]] && return
    grep -q "^ID=ubuntu" /etc/os-release 2>/dev/null || return
    if grep -rq "\buniverse\b" /etc/apt/sources.list /etc/apt/sources.list.d/ 2>/dev/null; then
        return  # already enabled
    fi
    info "Enabling Ubuntu universe repository..."
    if command -v add-apt-repository &>/dev/null; then
        add-apt-repository -y universe
    else
        # Fallback: append 'universe' to the first deb line in sources.list.
        sed -i '/^deb /s/ main$/ main universe/' /etc/apt/sources.list
    fi
    apt-get update -qq
    done_ "Ubuntu universe repository enabled."
}

# Ensure the NVIDIA CUDA repository is configured.
# If setup fails, BUILD_BACKEND is downgraded to "cpu" so installation continues.
_ensure_cuda_repo() {
    case "$DISTRO_FAMILY" in
        fedora)
            if dnf repolist enabled 2>/dev/null | grep -qi "cuda"; then
                skip "CUDA repository already enabled."
                return
            fi
            local ver; ver=$(rpm -E %fedora 2>/dev/null || echo 39)
            local url="https://developer.download.nvidia.com/compute/cuda/repos/fedora${ver}/x86_64/cuda-fedora${ver}.repo"
            info "Adding NVIDIA CUDA repo for Fedora ${ver} ..."
            if ! dnf config-manager --add-repo "$url" 2>/dev/null; then
                warn "Failed to add CUDA repo. Falling back to CPU build."
                warn "To add it manually: dnf config-manager --add-repo $url"
                BUILD_BACKEND="cpu"
                return
            fi
            dnf clean expire-cache -q
            done_ "NVIDIA CUDA repository added."
            ;;
        debian)
            if apt-cache policy 2>/dev/null | grep -qi "developer.download.nvidia.com"; then
                skip "CUDA repository already configured."
                return
            fi
            # shellcheck source=/dev/null
            . /etc/os-release
            local arch; arch=$(dpkg --print-architecture 2>/dev/null || echo x86_64)
            # Build a tag like ubuntu2404 or debian12.
            local distro_tag="${ID}${VERSION_ID//./}"
            local base="https://developer.download.nvidia.com/compute/cuda/repos/${distro_tag}/${arch}"
            info "Downloading NVIDIA CUDA keyring for ${PRETTY_NAME:-$ID} ..."
            if ! wget -q "$base/cuda-keyring_1.1-1_all.deb" -O /tmp/cuda-keyring.deb 2>/dev/null; then
                warn "Could not download CUDA keyring. Falling back to CPU build."
                warn "To add manually, see: https://developer.nvidia.com/cuda-downloads"
                BUILD_BACKEND="cpu"
                return
            fi
            dpkg -i /tmp/cuda-keyring.deb
            apt-get update -qq
            done_ "NVIDIA CUDA repository added."
            ;;
    esac
}

step_system_deps() {
    info "Checking system dependencies..."
    _PKGS_NEEDED=()
    # Note: _CLEANUP_PKGS is intentionally NOT reset here — it accumulates
    # across calls so step_cleanup_build_deps sees everything we installed.

    # On Ubuntu, ensure 'universe' repo is enabled — many packages live there.
    _ensure_universe_repo

    # ── Runtime dependencies (kept after install) ─────────────────────────────
    _need "command -v ydotool"        ydotool          ydotool
    _need "command -v notify-send"    libnotify        libnotify-bin
    _need "command -v pw-record"      pipewire-utils   pipewire-audio-client-libraries
    _need "command -v parecord"       pulseaudio-utils pulseaudio-utils
    _need "python3 -c 'import gi'"    python3-gobject  python3-gi
    _need "python3 -c 'import dbus'"  python3-dbus     python3-dbus
    _need "python3 -c 'import evdev'" python3-evdev    python3-evdev

    # ── Build-only dependencies (removed after whisper.cpp is compiled) ───────
    _build_need "command -v cmake"   cmake            cmake
    _build_need "command -v g++"     gcc-c++          g++
    _build_need "command -v git"     git              git
    _build_need "command -v lspci"   pciutils         pciutils

    # Backend-specific build deps
    case "$BUILD_BACKEND" in
        vulkan)
            _build_need "test -f /usr/include/vulkan/vulkan.h" vulkan-devel  libvulkan-dev
            _build_need "command -v glslc"                     glslc         glslang-tools
            ;;
        cuda)
            # CUDA packages are not in default repos — add the NVIDIA repo first.
            _ensure_cuda_repo
            # BUILD_BACKEND may have been downgraded to cpu if repo setup failed.
            if [[ "$BUILD_BACKEND" == "cuda" ]]; then
                _build_need "command -v nvcc" cuda-toolkit nvidia-cuda-toolkit
            fi
            ;;
    esac

    if [[ ${#_PKGS_NEEDED[@]} -eq 0 ]]; then
        skip "All system dependencies already present."
        return
    fi

    # Warn about any queued packages that are not found in the configured repos.
    local unavailable=()
    for pkg in "${_PKGS_NEEDED[@]}"; do
        _pkg_available "$pkg" || unavailable+=("$pkg")
    done
    if [[ ${#unavailable[@]} -gt 0 ]]; then
        warn "The following packages were not found in configured repositories and will be skipped:"
        for pkg in "${unavailable[@]}"; do
            warn "  - $pkg"
        done
        # Remove unavailable packages from the install list.
        local filtered=()
        for pkg in "${_PKGS_NEEDED[@]}"; do
            _pkg_available "$pkg" && filtered+=("$pkg")
        done
        _PKGS_NEEDED=("${filtered[@]}")
    fi

    if [[ ${#_PKGS_NEEDED[@]} -eq 0 ]]; then
        skip "All system dependencies already present (or unavailable in repos)."
        return
    fi

    info "Installing missing packages: ${_PKGS_NEEDED[*]}"
    case "$DISTRO_FAMILY" in
        fedora) dnf install -y "${_PKGS_NEEDED[@]}" ;;
        debian) apt-get update -qq && apt-get install -y "${_PKGS_NEEDED[@]}" ;;
    esac
    done_ "System dependencies installed."
}

# ── Step 3: Python dependencies ───────────────────────────────────────────────
step_python_deps() {
    # evdev is installed via the system package manager in step_system_deps;
    # this is a fallback in case the distro package is unavailable or outdated.
    if python3 -c "import evdev" &>/dev/null; then
        skip "python3-evdev already importable."
        return
    fi
    info "Installing python3-evdev via pip..."
    _pip_install evdev
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

    local -a cmake_flags=(-DBUILD_SHARED_LIBS=OFF -DCMAKE_BUILD_TYPE=Release)
    case "$BUILD_BACKEND" in
        vulkan)
            cmake_flags+=(-DGGML_VULKAN=ON  -DGGML_CUDA=OFF)
            info "Building with Vulkan backend (this may take several minutes)..."
            ;;
        cuda)
            cmake_flags+=(-DGGML_CUDA=ON    -DGGML_VULKAN=OFF)
            info "Building with CUDA backend (this may take several minutes)..."
            ;;
        cpu)
            cmake_flags+=(-DGGML_VULKAN=OFF -DGGML_CUDA=OFF)
            info "Building with CPU backend (this may take several minutes)..."
            ;;
    esac
    cmake -B "$BUILD_TMP/build" "$BUILD_TMP" "${cmake_flags[@]}"
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
# ── Step 5b: Remove build-only packages ──────────────────────────────────────
step_cleanup_build_deps() {
    if [[ ${#_CLEANUP_PKGS[@]} -eq 0 ]]; then
        skip "No build-only packages to remove."
        return
    fi
    info "Removing build-only packages: ${_CLEANUP_PKGS[*]}"
    case "$DISTRO_FAMILY" in
        fedora) dnf remove -y "${_CLEANUP_PKGS[@]}" ;;
        debian) apt-get remove -y "${_CLEANUP_PKGS[@]}" && apt-get autoremove -y ;;
    esac
    done_ "Build dependencies removed."
}

# ── Step 6: Install Python package ───────────────────────────────────────────
step_install_entry_point() {
    info "Installing whisper-transcribe Python package..."
    _pip_install "$SCRIPT_DIR"
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

    # PassEnvironment ensures DISPLAY/WAYLAND_DISPLAY reach the service on X11
    # sessions where the user manager may not inherit them automatically.
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
PassEnvironment=DISPLAY WAYLAND_DISPLAY XAUTHORITY DBUS_SESSION_BUS_ADDRESS

[Install]
WantedBy=graphical-session.target
EOF
    chown "$TARGET_USER:$TARGET_USER" "$service_file"

    local ydotoold_bin
    ydotoold_bin=$(command -v ydotoold 2>/dev/null || echo /usr/bin/ydotoold)

    local ydotool_file="$service_dir/ydotool.service"
    cat > "$ydotool_file" <<EOF
[Unit]
Description=ydotoold input daemon
After=graphical-session.target

[Service]
ExecStart=$ydotoold_bin
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

# ── Step 9: GNOME AppIndicator extension ─────────────────────────────────────
step_gnome_shell_ext() {
    # Only relevant if the target user is running a GNOME session right now.
    if ! pgrep -u "$TARGET_USER" gnome-shell &>/dev/null; then
        return
    fi

    local ext_id="appindicatorsupport@rgcjonas.gmail.com"
    local uid; uid=$(id -u "$TARGET_USER")
    local xdg_runtime="/run/user/$uid"
    local bus_addr="unix:path=$xdg_runtime/bus"

    info "GNOME session detected — checking AppIndicator extension..."

    # Check if already enabled
    if [[ -S "$xdg_runtime/bus" ]]; then
        local enabled
        enabled=$(sudo -u "$TARGET_USER" \
            XDG_RUNTIME_DIR="$xdg_runtime" \
            DBUS_SESSION_BUS_ADDRESS="$bus_addr" \
            gnome-extensions list --enabled 2>/dev/null || echo "")
        if echo "$enabled" | grep -qF "$ext_id"; then
            skip "GNOME AppIndicator extension already enabled."
            return
        fi
    fi

    # Install the package if it is available in the configured repositories.
    info "Installing GNOME AppIndicator extension package..."
    if _pkg_available gnome-shell-extension-appindicator; then
        case "$DISTRO_FAMILY" in
            fedora) dnf install -y gnome-shell-extension-appindicator ;;
            debian) apt-get install -y gnome-shell-extension-appindicator ;;
        esac
    else
        warn "Package 'gnome-shell-extension-appindicator' not found in configured repos."
        warn "Install it manually from: https://extensions.gnome.org/extension/615/appindicator-support/"
    fi

    # Try to enable it in the running session
    if [[ -S "$xdg_runtime/bus" ]]; then
        sudo -u "$TARGET_USER" \
            XDG_RUNTIME_DIR="$xdg_runtime" \
            DBUS_SESSION_BUS_ADDRESS="$bus_addr" \
            gnome-extensions enable "$ext_id" 2>/dev/null || true
    fi

    done_ "AppIndicator extension installed."
    echo "  NOTE: Log out and back in (or restart GNOME Shell) for the tray to appear."
}

# ── Step 10: Tray autostart ───────────────────────────────────────────────────
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

# ── Step 11: Done ─────────────────────────────────────────────────────────────
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
    local uninstall_flags=""
    pip3 uninstall --help 2>&1 | grep -q -- "--break-system-packages" \
        && uninstall_flags="--break-system-packages"
    pip3 uninstall $uninstall_flags -y whisper-transcribe 2>/dev/null || true
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
    detect_build_backend
    step_system_deps
    step_python_deps
    step_build_whisper
    step_download_model
    step_cleanup_build_deps
    step_install_entry_point
    step_input_group
    step_systemd_service
    step_gnome_shell_ext
    step_tray_autostart
    step_done
}

main
