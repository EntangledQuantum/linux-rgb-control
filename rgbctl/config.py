"""Paths, default settings, and load/save of state and profiles."""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
_XDG_CONFIG = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")  # empty = unset
CONFIG_DIR = _XDG_CONFIG / "rgbctl"
STATE_FILE = CONFIG_DIR / "state.json"
PROFILES_DIR = CONFIG_DIR / "profiles"
LOCK_FILE = CONFIG_DIR / "rgbctl.lock"
AUTOSTART_FILE = _XDG_CONFIG / "autostart" / "rgbctl.desktop"

OPENRGB_HOST = "127.0.0.1"
OPENRGB_PORT = 6742

# Fan-header settings are written by the setup wizard (`rgbctl setup`) or the Devices tab.
# Keys are "<device name>::<zone name>" → {"enabled": bool, "fans": int, "label": str}.
DEFAULT_STATE = {
    "effect": "rainbow_wave",
    "params": {
        "color1": "#ff0040",
        "color2": "#0080ff",
        "speed": 40,
        "brightness": 100,
        "rainbow": False,
        "temp_source": "cpu",
        "reverse": False,
        "sensitivity": 50,
        # Music tuning
        "bass_gain": 50, "mid_gain": 50, "treble_gain": 50,
        "beat_threshold": 30, "beat_gap": 220, "bass_cutoff": 160,
        "smoothing": 50, "noise_gate": 10, "music_floor": 4,
        # Interactive tuning
        "firefly_count": 3, "scroll_step": 15,
    },
    "fps": 30,
    "leds_per_fan": 8,
    "zones": {},
    # Devices are enabled by default; set False to leave one alone.
    "devices": {},
}


def _merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load_state() -> dict:
    try:
        data = json.loads(STATE_FILE.read_text())
    except (OSError, ValueError):
        data = {}
    return _merge(DEFAULT_STATE, data)


def save_state(state: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2))
    tmp.replace(STATE_FILE)


# A profile stores the look (effect + params), not the hardware layout.
def list_profiles() -> list[str]:
    if not PROFILES_DIR.is_dir():
        return []
    return sorted(p.stem for p in PROFILES_DIR.glob("*.json"))


def save_profile(name: str, state: dict) -> None:
    PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    data = {"effect": state["effect"], "params": state["params"]}
    (PROFILES_DIR / f"{name}.json").write_text(json.dumps(data, indent=2))


def load_profile(name: str, state: dict) -> dict:
    data = json.loads((PROFILES_DIR / f"{name}.json").read_text())
    new = copy.deepcopy(state)
    new["effect"] = data.get("effect", new["effect"])
    new["params"] = _merge(new["params"], data.get("params", {}))
    return new


def delete_profile(name: str) -> None:
    (PROFILES_DIR / f"{name}.json").unlink(missing_ok=True)
