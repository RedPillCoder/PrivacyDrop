"""Persistent user preferences for PrivacyDrop.

Settings are stored locally and never transmitted anywhere (no telemetry).
Only non-sensitive preference values are saved — never file names or paths.

The config location is (in priority order):
    1. $PRIVACYDROP_CONFIG        (used by tests / portable mode)
    2. %APPDATA%\\PrivacyDrop\\config.json   (standard Windows location)
    3. ~/.privacydrop.json         (fallback)
"""

from __future__ import annotations

import json
import os
import tempfile

DEFAULTS = {
    "suffix": "_clean",
    "subfolder": False,
    "strip_icc": False,
    "keep_attachments": False,
    "remove_scripts": True,
    "topmost": False,
}

# Characters that are invalid in Windows file names — a user-typed suffix
# must never be able to create a broken path.
_BAD_SUFFIX_CHARS = set('/\\:*?"<>|')


def config_path() -> str:
    env = os.environ.get("PRIVACYDROP_CONFIG")
    if env:
        return env
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    if os.environ.get("APPDATA"):
        return os.path.join(base, "PrivacyDrop", "config.json")
    return os.path.join(base, ".privacydrop.json")


def _safe_suffix(val: str) -> str:
    s = "".join(c for c in val if c not in _BAD_SUFFIX_CHARS and ord(c) >= 32)
    return s if s else DEFAULTS["suffix"]


def _coerce(settings) -> dict:
    """Merge user settings over defaults, sanitizing values by type.

    Malformed or hostile config files can never inject bad values: booleans
    must be real booleans, the suffix is filename-sanitized and length-capped.
    """
    merged = dict(DEFAULTS)
    if not isinstance(settings, dict):
        return merged
    for key, default in DEFAULTS.items():
        val = settings.get(key)
        if isinstance(default, bool):
            if isinstance(val, bool):
                merged[key] = val
        elif isinstance(default, str):
            if isinstance(val, str) and len(val) <= 64:
                merged[key] = _safe_suffix(val) if key == "suffix" else val
    return merged


def load() -> dict:
    try:
        with open(config_path(), "r", encoding="utf-8") as f:
            return _coerce(json.load(f))
    except Exception:
        return dict(DEFAULTS)


def save(settings: dict) -> None:
    """Atomically write the current settings (temp file + rename)."""
    path = config_path()
    d = os.path.dirname(path) or "."
    os.makedirs(d, exist_ok=True)
    payload = json.dumps(_coerce(settings), indent=2)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".pd-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(payload)
        # Set restrictive permissions on config file (owner read/write only)
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass  # Not critical on Windows
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
