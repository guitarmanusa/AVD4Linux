"""Persistent user settings for AVD4Linux device redirection.

Stores optional local microphone and webcam pass-through preferences in a
user-only (0o600) JSON file. Both devices are opt-in so that enabling the
application never silently exposes the local capture hardware to a remote
desktop session.
"""
from __future__ import annotations

import json
import logging
import os
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

CONFIG_DIR = Path.home() / ".config" / "avd4linux"
SETTINGS_PATH = CONFIG_DIR / "settings.json"


@dataclass
class Settings:
    """User preferences applied to each FreeRDP session launch."""

    microphone_enabled: bool = False
    webcam_enabled: bool = False
    sound_enabled: bool = True
    # Empty means "auto-select the PIV Authentication certificate". Otherwise this
    # holds a user-supplied selector: an exact label, a label substring, a hex
    # object ID, or a full pkcs11: URI.
    piv_certificate_selector: str = ""

    @classmethod
    def load(cls, path: Path | None = None) -> "Settings":
        """Loads persisted settings, falling back to privacy-safe defaults.

        Any read/parse/schema failure degrades to defaults rather than raising,
        so a corrupt settings file can never prevent the app from starting.
        """
        target = Path(path) if path is not None else SETTINGS_PATH
        try:
            raw = target.read_text(encoding="utf-8")
        except FileNotFoundError:
            logger.debug("No settings file at %s; using defaults", target)
            return cls()
        except OSError as e:
            logger.warning("Could not read settings from %s: %s; using defaults", target, e)
            return cls()

        try:
            data = json.loads(raw)
        except ValueError as e:
            logger.warning("Corrupt settings file %s: %s; using defaults", target, e)
            return cls()

        if not isinstance(data, dict):
            logger.warning("Settings file %s is not a JSON object; using defaults", target)
            return cls()

        return cls(
            microphone_enabled=cls._read_bool(data, "microphone_enabled", False),
            webcam_enabled=cls._read_bool(data, "webcam_enabled", False),
            sound_enabled=cls._read_bool(data, "sound_enabled", True),
            piv_certificate_selector=cls._read_str(data, "piv_certificate_selector", ""),
        )

    def save(self, path: Path | None = None) -> bool:
        """Atomically persists settings with user-only permissions.

        Returns True on success; failures are logged and reported rather than
        raised so that a read-only home directory cannot break a session launch.
        """
        target = Path(path) if path is not None else SETTINGS_PATH
        payload = {
            "microphone_enabled": self.microphone_enabled,
            "webcam_enabled": self.webcam_enabled,
            "sound_enabled": self.sound_enabled,
            "piv_certificate_selector": self.piv_certificate_selector,
        }
        try:
            # Only tighten permissions on a directory we create ourselves; never
            # silently re-permission a pre-existing user directory.
            try:
                target.parent.mkdir(parents=True, mode=stat.S_IRWXU)
                created_dir = True
            except FileExistsError:
                created_dir = False
            if created_dir:
                try:
                    os.chmod(target.parent, stat.S_IRWXU)
                except OSError as e:
                    logger.debug("Could not tighten permissions on %s: %s", target.parent, e)

            fd, tmp_path = tempfile.mkstemp(dir=str(target.parent), prefix=".settings-", suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(payload, f, indent=2)
                    f.write("\n")
                os.chmod(tmp_path, stat.S_IRUSR | stat.S_IWUSR)
                os.replace(tmp_path, target)
            finally:
                if os.path.exists(tmp_path):
                    try:
                        os.unlink(tmp_path)
                    except OSError:
                        pass
            logger.info("Saved settings to %s", target)
            return True
        except Exception as e:
            logger.warning("Could not save settings to %s: %s", target, e)
            return False

    @staticmethod
    def _read_bool(data: dict, key: str, default: bool) -> bool:
        """Reads a boolean key, ignoring absent or wrongly-typed entries."""
        if key not in data:
            return default
        value = data[key]
        if isinstance(value, bool):
            return value
        logger.warning("Ignoring non-boolean value for %s: %r", key, value)
        return default

    @staticmethod
    def _read_str(data: dict, key: str, default: str) -> str:
        """Reads a string key, ignoring absent or wrongly-typed entries."""
        if key not in data:
            return default
        value = data[key]
        if isinstance(value, str):
            return value
        logger.warning("Ignoring non-string value for %s: %r", key, value)
        return default
