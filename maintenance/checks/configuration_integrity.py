"""
Configuration Integrity Check
Verifies: configuration filenames, configuration paths,
          missing configuration files, platform compatibility.
"""

import json
import os
from pathlib import Path


EXPECTED_CONFIG_FILES = {
    "configuration/memory.json": {"required_keys": []},
    "configuration/tasks.json": {"required_keys": []},
    "configuration/brain_config.json": {"required_keys": []},
    "configuration/brain_registry.json": {"required_keys": []},
    "configuration/project_context.json": {"required_keys": []},
    "configuration/permissions.json": {"required_keys": []},
}

# requirements file — expected name
REQUIREMENTS_FILE = "configuration/requirements (1).txt"


def run(project_root: str) -> dict:
    issues = []
    root = Path(project_root)

    # --- Missing configuration files ---
    for cfg_path in EXPECTED_CONFIG_FILES:
        full = root / cfg_path
        if not full.exists():
            issues.append(f"MISSING_CONFIG: {cfg_path}")

    # --- Validate JSON files are parseable ---
    for cfg_path in EXPECTED_CONFIG_FILES:
        full = root / cfg_path
        if not full.exists():
            continue
        try:
            with open(full, encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError as exc:
            issues.append(f"INVALID_JSON: {cfg_path} — {exc}")
            continue
        except Exception as exc:
            issues.append(f"UNREADABLE_CONFIG: {cfg_path} — {exc}")
            continue

        # Required keys check
        for key in EXPECTED_CONFIG_FILES[cfg_path]["required_keys"]:
            if key not in data:
                issues.append(f"MISSING_KEY: {cfg_path} missing '{key}'")

    # --- Requirements file ---
    req_path = root / REQUIREMENTS_FILE
    if not req_path.exists():
        # Check if a standard requirements.txt exists
        alt = root / "requirements.txt"
        if not alt.exists():
            issues.append(f"MISSING_REQUIREMENTS: {REQUIREMENTS_FILE} not found")
        else:
            issues.append(
                f"REQUIREMENTS_FILENAME: standard requirements.txt found at root "
                f"but expected at {REQUIREMENTS_FILE}"
            )

    # --- Platform compatibility: check for Windows-incompatible paths ---
    # (colons, forward-slash-only assumptions in hardcoded paths)
    config_dir = root / "configuration"
    if config_dir.exists():
        for entry in config_dir.iterdir():
            if entry.is_file():
                # Check for filenames with characters invalid on Windows
                invalid_chars = set('<>:"/\\|?*')
                name = entry.name
                # Allow the space in "requirements (1).txt" — it's intentional
                bad = [c for c in name if c in invalid_chars]
                if bad:
                    issues.append(
                        f"PLATFORM_INCOMPATIBLE_NAME: {entry.relative_to(root)} "
                        f"contains {bad}"
                    )

    # --- Check for hardcoded absolute paths in config files ---
    for cfg_path in EXPECTED_CONFIG_FILES:
        full = root / cfg_path
        if not full.exists():
            continue
        try:
            text = full.read_text(encoding="utf-8")
            if "C:\\" in text or "D:\\" in text or "/home/" in text:
                issues.append(
                    f"HARDCODED_PATH: {cfg_path} contains absolute path reference"
                )
        except Exception:
            pass

    return {
        "check": "configuration_integrity",
        "issues": issues,
        "passed": len(issues) == 0,
    }
