"""
Dependency Integrity Check
Verifies: installed packages, missing packages,
          requirements.txt consistency, unused dependencies.
"""

import ast
import importlib.util
import os
import re
import sys
from pathlib import Path


REQUIREMENTS_FILE = "configuration/requirements (1).txt"

# Packages that are tricky to import-check by name (import name differs from dist name)
IMPORT_NAME_MAP = {
    "python-dotenv": "dotenv",
    "pillow": "PIL",
    "pyyaml": "yaml",
    "beautifulsoup4": "bs4",
    "scikit-learn": "sklearn",
    "python-dateutil": "dateutil",
    "gitpython": "git",
    "aiohttp": "aiohttp",
    "typing-inspection": "typing_inspection",
    "uuid-utils": "uuid_utils",
    "annotated-types": "annotated_types",
    "markdown-it-py": "markdown_it",
}

# Packages only needed at install time — skip unused check
INSTALL_ONLY = {"pip", "setuptools", "wheel"}


def _parse_requirements(req_path: Path) -> list[str]:
    packages = []
    try:
        for line in req_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            # Strip version specifier
            name = re.split(r"[=><!~\[]", line)[0].strip().lower()
            if name:
                packages.append(name)
    except Exception:
        pass
    return packages


def _collect_used_imports(project_root: Path) -> set[str]:
    used = set()
    python_files = [
        p for p in project_root.rglob("*.py")
        if ".venv" not in p.parts
        and "__pycache__" not in p.parts
        and "maintenance" not in p.parts
    ]
    for filepath in python_files:
        try:
            source = filepath.read_text(encoding="utf-8")
            tree = ast.parse(source)
        except Exception:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    used.add(alias.name.split(".")[0].lower())
            elif isinstance(node, ast.ImportFrom):
                if node.module and not node.level:
                    used.add(node.module.split(".")[0].lower())
    return used


def run(project_root: str) -> dict:
    issues = []
    root = Path(project_root)

    req_path = root / REQUIREMENTS_FILE
    if not req_path.exists():
        issues.append(f"MISSING_REQUIREMENTS: {REQUIREMENTS_FILE}")
        return {
            "check": "dependency_integrity",
            "issues": issues,
            "passed": False,
        }

    required_packages = _parse_requirements(req_path)

    # --- Missing packages (not importable) ---
    for pkg_name in required_packages:
        if pkg_name in INSTALL_ONLY:
            continue
        import_name = IMPORT_NAME_MAP.get(pkg_name, pkg_name.replace("-", "_"))
        if import_name in sys.modules:
            continue
        spec = importlib.util.find_spec(import_name)
        if spec is None:
            issues.append(f"MISSING_PACKAGE: {pkg_name} (import: {import_name})")

    # --- Unused dependencies ---
    used_imports = _collect_used_imports(root)

    for pkg_name in required_packages:
        if pkg_name in INSTALL_ONLY:
            continue
        import_name = IMPORT_NAME_MAP.get(pkg_name, pkg_name.replace("-", "_"))
        canonical = import_name.lower()
        if canonical not in used_imports:
            issues.append(f"UNUSED_DEPENDENCY: {pkg_name} — not imported in project source")

    return {
        "check": "dependency_integrity",
        "issues": issues,
        "passed": len(issues) == 0,
    }
