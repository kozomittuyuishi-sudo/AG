"""
Import Integrity Check
Checks: broken imports, wrong paths, missing modules, circular imports,
        relative import issues, absolute import issues.
"""

import ast
import os
import sys
import importlib
import importlib.util
from pathlib import Path


def run(project_root: str) -> dict:
    issues = []
    root = Path(project_root)

    python_files = [
        p for p in root.rglob("*.py")
        if ".venv" not in p.parts
        and "__pycache__" not in p.parts
        and "maintenance" not in p.parts
        and "node_modules" not in p.parts
    ]

    # --- Collect all imports per file ---
    for filepath in python_files:
        try:
            source = filepath.read_text(encoding="utf-8")
        except Exception as exc:
            issues.append(f"UNREADABLE: {filepath.relative_to(root)} — {exc}")
            continue

        try:
            tree = ast.parse(source, filename=str(filepath))
        except SyntaxError as exc:
            issues.append(f"SYNTAX_ERROR: {filepath.relative_to(root)} — {exc}")
            continue

        rel = filepath.relative_to(root)

        for node in ast.walk(tree):
            # Relative import check
            if isinstance(node, ast.ImportFrom) and node.level and node.level > 0:
                issues.append(
                    f"RELATIVE_IMPORT: {rel} line {node.lineno} — "
                    f"{'.' * node.level}{node.module or ''}"
                )

            # Absolute import — verify module exists in venv or stdlib
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                if isinstance(node, ast.Import):
                    names = [alias.name.split(".")[0] for alias in node.names]
                else:
                    if node.level and node.level > 0:
                        continue  # already flagged above
                    if not node.module:
                        continue
                    names = [node.module.split(".")[0]]

                for name in names:
                    if name in sys.stdlib_module_names:
                        continue
                    if name in sys.modules:
                        continue
                    spec = importlib.util.find_spec(name)
                    if spec is None:
                        # Check if it's a local project package (root or subdirectory)
                        local_pkg = root / name
                        local_mod = root / f"{name}.py"
                        # Also check as a sub-package anywhere in the tree
                        sub_pkgs = list(root.rglob(name))
                        is_local = (
                            local_pkg.is_dir()
                            or local_mod.exists()
                            or any(p.is_dir() for p in sub_pkgs if ".venv" not in p.parts and "node_modules" not in p.parts)
                        )
                        if not is_local:
                            issues.append(
                                f"MISSING_MODULE: {rel} line {node.lineno} — {name}"
                            )

    # --- Circular import detection (static, via import graph) ---
    import_graph: dict[str, list[str]] = {}

    for filepath in python_files:
        try:
            source = filepath.read_text(encoding="utf-8")
            tree = ast.parse(source)
        except Exception:
            continue

        mod_key = str(filepath.relative_to(root))
        deps = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module and not node.level:
                deps.append(node.module.split(".")[0])
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    deps.append(alias.name.split(".")[0])
        import_graph[mod_key] = list(set(deps))

    # Simple DFS cycle detection
    def _has_cycle(graph: dict) -> list[str]:
        visited = set()
        path = []

        def dfs(node):
            if node in path:
                return path[path.index(node):]
            if node in visited:
                return []
            visited.add(node)
            path.append(node)
            for dep in graph.get(node, []):
                dep_key = next(
                    (k for k in graph if Path(k).stem == dep), None
                )
                if dep_key:
                    cycle = dfs(dep_key)
                    if cycle:
                        return cycle
            path.pop()
            return []

        for node in graph:
            if node not in visited:
                cycle = dfs(node)
                if cycle:
                    return cycle
        return []

    cycle = _has_cycle(import_graph)
    if cycle:
        issues.append(f"CIRCULAR_IMPORT: {' → '.join(cycle)}")

    return {
        "check": "import_integrity",
        "issues": issues,
        "passed": len(issues) == 0,
    }
