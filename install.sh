#!/usr/bin/env bash
# RGB Control installer — one command, step by step:
#   1 system check & packages   2 Python environment   3 OpenRGB   4 device permissions
#   5 app menu + `rgbctl` command   6 find devices & map your fans   7 done
#
# Usage: ./install.sh [--yes] [--no-system] [--no-setup] [--uninstall]
#   --yes        accept defaults, no questions (setup wizard runs with --auto)
#   --no-system  skip steps that need sudo (packages, device permissions)
#   --no-setup   don't run the device setup wizard at the end
#   --uninstall  remove RGB Control (keeps your settings unless you say otherwise)
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA="${XDG_DATA_HOME:-$HOME/.local/share}/rgbctl"
APPS="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
CONF="${XDG_CONFIG_HOME:-$HOME/.config}"
BIN="$HOME/.local/bin"
OPENRGB_VER="1.1"
OPENRGB_URL="https://codeberg.org/OpenRGB/OpenRGB/releases/download/release_1.1/OpenRGB_1.1_x86_64_8e16de2.AppImage"
OPENRGB_SHA256="d556c2273b0ef863dbee7ffdb438304b382add5d685c93c60758b42de3b0268d"

YES=0; NOSYS=0; NOSETUP=0; UNINSTALL=0
for a in "$@"; do
  case "$a" in
    -y|--yes) YES=1 ;;
    --no-system) NOSYS=1 ;;
    --no-setup) NOSETUP=1 ;;
    --uninstall) UNINSTALL=1 ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    *) echo "Unknown option: $a"; exit 2 ;;
  esac
done

if [ -t 1 ]; then B=$'\033[1m'; D=$'\033[2m'; G=$'\033[32m'; Y=$'\033[33m'; RD=$'\033[31m'; R=$'\033[0m'
else B=; D=; G=; Y=; RD=; R=; fi
TOTAL=7
step() { echo; echo "${B}[$1/$TOTAL] $2${R}"; }
ok()   { echo "  ${G}✓${R} $*"; }
warn() { echo "  ${Y}!${R} $*"; }
die()  { echo "  ${RD}✗ $*${R}"; exit 1; }
ask()  { # ask "question" default(y/n)
  local def="$2" ans
  if [ "$YES" = 1 ]; then [ "$def" = y ]; return; fi
  read -r -p "  $1 $( [ "$def" = y ] && echo '[Y/n]' || echo '[y/N]' ) " ans </dev/tty || ans=""
  ans="${ans:-$def}"; [[ "$ans" =~ ^[Yy] ]]
}

# ---------------------------------------------------------------------------- uninstall
if [ "$UNINSTALL" = 1 ]; then
  echo "${B}Removing RGB Control${R}"
  pkill -f "$DIR/.venv/bin/python -m rgbctl" 2>/dev/null || true
  rm -f "$BIN/rgbctl" "$APPS/rgbctl.desktop" "$CONF/autostart/rgbctl.desktop"
  rm -rf "$DATA"
  ok "Removed the app menu entry, the rgbctl command, autostart and the downloaded OpenRGB"
  if ask "Also delete your settings and profiles (~/.config/rgbctl)?" n; then rm -rf "$CONF/rgbctl"; ok "Settings deleted"; fi
  if [ -f /etc/udev/rules.d/60-openrgb.rules ] && ask "Remove the device permission rules (needs sudo)?" n; then
    sudo rm -f /etc/udev/rules.d/60-openrgb.rules /etc/udev/rules.d/60-rgbctl-i2c.rules
    sudo udevadm control --reload-rules || true
    ok "Permission rules removed"
  fi
  echo "  The project folder ($DIR) is untouched; delete it yourself if you like."
  exit 0
fi

cat <<EOF

${B}  ✨ RGB Control installer${R}
  ${D}Control and sync every RGB light on your PC, from Linux.${R}
EOF

# ---------------------------------------------------------------------------- 1. system
step 1 "Checking your system"
[ "$(uname -s)" = Linux ] || die "This app is for Linux."
ARCH="$(uname -m)"
[ "$ARCH" = x86_64 ] || warn "Architecture $ARCH: the bundled OpenRGB download is x86_64 only. Install OpenRGB from your distro instead."
. /etc/os-release 2>/dev/null || true
ok "${PRETTY_NAME:-Linux} ($ARCH)"

PM=""
for p in apt-get dnf pacman zypper; do command -v "$p" >/dev/null && { PM="$p"; break; }; done

PY="${PYTHON:-python3}"
need=()
if ! command -v "$PY" >/dev/null; then need+=(python); fi
if command -v "$PY" >/dev/null && ! "$PY" -c 'import sys; assert sys.version_info >= (3, 9)' 2>/dev/null; then
  die "Python 3.9+ is required (found $("$PY" -V 2>&1))."
fi
if command -v "$PY" >/dev/null && ! "$PY" -c 'import venv, ensurepip' 2>/dev/null; then need+=(venv); fi
command -v curl >/dev/null || command -v wget >/dev/null || need+=(curl)
command -v parec >/dev/null || need+=(parec)
"$PY" - <<'PYEOF' 2>/dev/null || need+=(fuse2)
import ctypes.util, sys
sys.exit(0 if ctypes.util.find_library("fuse") else 1)
PYEOF

pkgs_for() { # map generic needs → package names for this package manager
  local out=()
  for n in "$@"; do
    case "$PM:$n" in
      apt-get:python) out+=(python3) ;; apt-get:venv) out+=(python3-venv) ;;
      apt-get:curl) out+=(curl) ;; apt-get:parec) out+=(pulseaudio-utils) ;;
      apt-get:fuse2) if apt-cache show libfuse2t64 >/dev/null 2>&1; then out+=(libfuse2t64); else out+=(libfuse2); fi ;;
      dnf:python|dnf:venv) out+=(python3) ;; dnf:curl) out+=(curl) ;;
      dnf:parec) out+=(pulseaudio-utils) ;; dnf:fuse2) out+=(fuse-libs) ;;
      pacman:python|pacman:venv) out+=(python) ;; pacman:curl) out+=(curl) ;;
      pacman:parec) out+=(libpulse) ;; pacman:fuse2) out+=(fuse2) ;;
      zypper:python|zypper:venv) out+=(python3) ;; zypper:curl) out+=(curl) ;;
      zypper:parec) out+=(pulseaudio-utils) ;; zypper:fuse2) out+=(libfuse2) ;;
    esac
  done
  echo "${out[@]:-}"
}

if [ ${#need[@]} -eq 0 ]; then
  ok "Python $("$PY" -c 'import platform; print(platform.python_version())'), downloader, audio capture and AppImage support present"
else
  pk="$(pkgs_for "${need[@]}")"
  warn "Missing: ${need[*]}  ${D}(fuse2 lets OpenRGB's AppImage run; parec lets music effects hear your audio)${R}"
  if [ "$NOSYS" = 0 ] && [ -n "$PM" ] && [ -n "$pk" ] && ask "Install them now with $PM (needs sudo): $pk ?" y; then
    case "$PM" in
      apt-get) sudo apt-get update -qq && sudo apt-get install -y $pk ;;
      dnf) sudo dnf install -y $pk ;;
      pacman) sudo pacman -S --needed --noconfirm $pk ;;
      zypper) sudo zypper --non-interactive install $pk ;;
    esac
    ok "Installed $pk"
  else
    for n in "${need[@]}"; do
      case "$n" in python|venv|curl) die "Please install: $pk (or the equivalent for your distro), then re-run." ;; esac
    done
    warn "Continuing without: ${need[*]} (OpenRGB will self-extract; music effects need parec)"
  fi
fi

# ---------------------------------------------------------------------------- 2. python env
step 2 "Setting up the Python environment"
if [ ! -x "$DIR/.venv/bin/python" ]; then "$PY" -m venv "$DIR/.venv"; fi
"$DIR/.venv/bin/python" -m pip install -q --upgrade pip
"$DIR/.venv/bin/python" -m pip install -q -r "$DIR/requirements.txt"
ok "Dependencies installed in $DIR/.venv  ${D}(PySide6, openrgb-python, numpy, python-xlib, psutil, nvidia-ml-py)${R}"

# ---------------------------------------------------------------------------- 3. openrgb
step 3 "Getting OpenRGB (the hardware layer)"
OPENRGB=""
if command -v openrgb >/dev/null; then
  OPENRGB="$(command -v openrgb)"
  ok "Using installed OpenRGB: $OPENRGB  ${D}($("$OPENRGB" --version 2>/dev/null | head -1 || true))${R}"
elif [ -x "$DATA/OpenRGB.AppImage" ] && echo "$OPENRGB_SHA256  $DATA/OpenRGB.AppImage" | sha256sum -c --quiet 2>/dev/null; then
  OPENRGB="$DATA/OpenRGB.AppImage"
  ok "OpenRGB $OPENRGB_VER already downloaded"
else
  mkdir -p "$DATA"
  echo "  Downloading OpenRGB $OPENRGB_VER from codeberg.org (≈36 MB)…"
  tmp="$DATA/OpenRGB.AppImage.part"
  if command -v curl >/dev/null; then curl -fL --progress-bar -o "$tmp" "$OPENRGB_URL"; else wget -q --show-progress -O "$tmp" "$OPENRGB_URL"; fi
  echo "$OPENRGB_SHA256  $tmp" | sha256sum -c --quiet || { rm -f "$tmp"; die "Checksum mismatch: download corrupted or tampered with."; }
  mv "$tmp" "$DATA/OpenRGB.AppImage"; chmod +x "$DATA/OpenRGB.AppImage"
  OPENRGB="$DATA/OpenRGB.AppImage"
  ok "OpenRGB $OPENRGB_VER downloaded and verified (sha256)"
fi
run_openrgb() { if [[ "$OPENRGB" == *.AppImage ]] && ! "$PY" -c 'import ctypes.util,sys; sys.exit(0 if ctypes.util.find_library("fuse") else 1)' 2>/dev/null; then
  APPIMAGE_EXTRACT_AND_RUN=1 "$OPENRGB" "$@"; else "$OPENRGB" "$@"; fi; }

# ---------------------------------------------------------------------------- 4. permissions
step 4 "Device permissions"
echo "  ${D}Lets RGB Control talk to USB RGB controllers and SMBus/I2C devices (GPU, RAM, some boards) without root.${R}"
if [ "$NOSYS" = 1 ]; then
  warn "Skipped (--no-system)"
else
  rules="$(mktemp)"; run_openrgb --print-udev-rules > "$rules" 2>/dev/null || true
  i2c_rule='KERNEL=="i2c-[0-9]*", GROUP="i2c", MODE="0660", TAG+="uaccess"'
  have_rules=0
  { [ -f /etc/udev/rules.d/60-openrgb.rules ] || [ -f /usr/lib/udev/rules.d/60-openrgb.rules ] || [ -f /lib/udev/rules.d/60-openrgb.rules ]; } && have_rules=1
  have_i2c=0; [ -f /etc/udev/rules.d/60-rgbctl-i2c.rules ] && have_i2c=1
  if [ $have_rules = 1 ] && [ $have_i2c = 1 ] && lsmod | grep -q '^i2c_dev'; then
    ok "Already set up"
  elif ask "Install device permission rules (needs sudo)?" y; then
    if [ $have_rules = 0 ] && [ -s "$rules" ]; then sudo install -m 644 "$rules" /etc/udev/rules.d/60-openrgb.rules; ok "USB/HID rules (from OpenRGB)"; fi
    echo "$i2c_rule" | sudo tee /etc/udev/rules.d/60-rgbctl-i2c.rules >/dev/null
    sudo groupadd -f i2c
    sudo usermod -aG i2c "$USER" || true
    echo i2c-dev | sudo tee /etc/modules-load.d/i2c-dev.conf >/dev/null
    sudo modprobe i2c-dev || true
    if grep -q AuthenticAMD /proc/cpuinfo; then sudo modprobe i2c-piix4 2>/dev/null || true; else sudo modprobe i2c-i801 2>/dev/null || true; fi
    sudo udevadm control --reload-rules && sudo udevadm trigger
    ok "I2C/SMBus access (i2c-dev loaded at boot, you're in the i2c group)"
  else
    warn "Skipped: some devices may not be detected"
  fi
  rm -f "$rules"
fi

# ---------------------------------------------------------------------------- 5. app integration
step 5 "Adding RGB Control to your app menu"
mkdir -p "$BIN" "$APPS"
chmod +x "$DIR/bin/rgbctl"
ln -sf "$DIR/bin/rgbctl" "$BIN/rgbctl"
cat > "$APPS/rgbctl.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=RGB Control
GenericName=RGB Lighting
Comment=Control and sync fan, GPU and peripheral RGB lighting
Exec=$DIR/bin/rgbctl
Icon=$DIR/assets/rgbctl.svg
Categories=Utility;Settings;HardwareSettings;
Keywords=rgb;led;fan;openrgb;lighting;
Terminal=false
EOF
update-desktop-database "$APPS" >/dev/null 2>&1 || true
ok "App menu: 'RGB Control'   Command: rgbctl"
case ":$PATH:" in *":$BIN:"*) ;; *) warn "$BIN is not on your PATH; add it to use 'rgbctl' in a terminal" ;; esac
[ "${XDG_SESSION_TYPE:-}" = wayland ] && warn "Wayland session: everything works except the mouse/keyboard-reactive effects (they need X11)"

# ---------------------------------------------------------------------------- 6. setup
step 6 "Finding your devices and mapping your fans"
if [ "$NOSETUP" = 1 ]; then
  warn "Skipped (--no-setup). Run it any time: rgbctl setup"
else
  export RGBCTL_OPENRGB="$OPENRGB"
  if [ "$YES" = 1 ]; then "$DIR/bin/rgbctl" setup --auto || warn "Setup didn't finish; run: rgbctl setup"
  else "$DIR/bin/rgbctl" setup </dev/tty || warn "Setup didn't finish; run: rgbctl setup"; fi
fi

# ---------------------------------------------------------------------------- 7. done
step 7 "Done"
ok "RGB Control is installed."
if id -nG "$USER" | grep -qw i2c; then :; else
  [ "$NOSYS" = 0 ] && warn "Log out and back in once so the new i2c group membership applies (GPU/RAM RGB)."
fi
if [ "$YES" = 0 ] && [ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ] && ask "Open RGB Control now?" y; then
  nohup "$DIR/bin/rgbctl" >/dev/null 2>&1 &
  ok "Launched. Look for the rainbow ring icon in your top bar."
fi
echo
