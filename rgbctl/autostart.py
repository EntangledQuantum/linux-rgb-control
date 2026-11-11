"""Start-at-login via an XDG autostart entry (works on GNOME/KDE/etc.)."""
from __future__ import annotations

from .config import AUTOSTART_FILE, PROJECT_DIR

LAUNCHER = PROJECT_DIR / "bin" / "rgbctl"

ENTRY = f"""[Desktop Entry]
Type=Application
Name=RGB Control
Comment=Control and sync fan RGB lighting
Exec={LAUNCHER} --tray
Icon={PROJECT_DIR / "assets" / "rgbctl.svg"}
X-GNOME-Autostart-enabled=true
X-GNOME-Autostart-Delay=5
Terminal=false
"""


def is_enabled() -> bool:
    return AUTOSTART_FILE.exists()


def set_enabled(on: bool) -> None:
    if on:
        AUTOSTART_FILE.parent.mkdir(parents=True, exist_ok=True)
        AUTOSTART_FILE.write_text(ENTRY)
    else:
        AUTOSTART_FILE.unlink(missing_ok=True)
