"""
maintenance.py — Project AB Maintenance Orchestrator

Executes all checks independently and prints a concise summary.
Usage:  python maintenance/maintenance.py
"""

import io
import os
import sys
from pathlib import Path

# Force UTF-8 output on Windows to avoid encoding errors with special chars
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# Ensure project root is on sys.path
_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_root))

from maintenance.checks import (
    import_integrity,
    runtime_integrity,
    repository_integrity,
    configuration_integrity,
    dependency_integrity,
    pytest_validation,
)

PROJECT_ROOT = str(_root)


def _run_check(module, label: str) -> dict:
    try:
        result = module.run(PROJECT_ROOT)
    except Exception as exc:
        result = {
            "check": label,
            "issues": [f"CHECK_CRASHED: {exc}"],
            "passed": False,
        }
    return result


def main():
    checks = [
        (import_integrity,       "Import Integrity"),
        (runtime_integrity,      "Runtime Integrity"),
        (repository_integrity,   "Repository Integrity"),
        (configuration_integrity,"Configuration Integrity"),
        (dependency_integrity,   "Dependency Integrity"),
        (pytest_validation,      "Pytest Validation"),
    ]

    results = []
    for module, label in checks:
        print(f"  Running: {label}...", flush=True)
        result = _run_check(module, label)
        result["label"] = label
        results.append(result)

    print()
    print("=" * 60)
    print("MAINTENANCE REPORT")
    print("=" * 60)

    all_passed = True
    for result in results:
        label   = result["label"]
        passed  = result.get("passed", False)
        issues  = result.get("issues", [])
        summary = result.get("summary", "")

        status = "PASS" if passed else "FAIL"
        if not passed:
            all_passed = False

        print(f"[{status}] {label}")
        if summary:
            print(f"       {summary}")
        if not passed and issues:
            for issue in issues[:10]:  # cap at 10 per check
                print(f"       ! {issue}")
            if len(issues) > 10:
                print(f"       ... and {len(issues) - 10} more issue(s)")

    print("=" * 60)
    print(f"Overall: {'PASSED' if all_passed else 'FAILED'}")
    print("=" * 60)

    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
