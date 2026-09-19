"""
Pytest Validation Check
Runs pytest and captures failures only.
"""

import subprocess
import sys
from pathlib import Path


def run(project_root: str) -> dict:
    issues = []

    result = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/", "-x", "--tb=short", "-q"],
        capture_output=True,
        text=True,
        cwd=project_root,
    )

    stdout = result.stdout.strip()
    stderr = result.stderr.strip()

    passed = result.returncode == 0

    if not passed:
        # Extract only failure lines
        failure_lines = []
        in_failure = False
        for line in stdout.splitlines():
            if line.startswith("FAILED") or "ERROR" in line or "AssertionError" in line:
                failure_lines.append(line)
                in_failure = True
            elif line.startswith("=") and "failed" in line.lower():
                failure_lines.append(line)
            elif in_failure and line.startswith(" "):
                failure_lines.append(line)
            else:
                in_failure = False

        if not failure_lines:
            # Fallback: include last 20 lines of output
            failure_lines = stdout.splitlines()[-20:]

        issues.extend(failure_lines)

        if stderr:
            issues.append(f"STDERR: {stderr[:500]}")

    # Always capture the summary line (passed/failed count)
    summary = ""
    for line in stdout.splitlines():
        if "passed" in line or "failed" in line or "error" in line:
            summary = line.strip()
            break

    return {
        "check": "pytest_validation",
        "issues": issues,
        "passed": passed,
        "summary": summary,
    }
