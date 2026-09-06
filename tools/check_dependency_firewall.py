"""Fail when a production tree depends on benchmark packages.

Usage: python tools/check_dependency_firewall.py path/to/production [...]
"""

from __future__ import annotations

import ast
from pathlib import Path
import re
import sys

BANNED_IMPORT_ROOTS = frozenset(
    {"benchmark_core", "autonomous_dev_bench", "suites", "oracles", "mutations", "faults"}
)
DEPENDENCY_PATTERN = re.compile(
    r"(?i)(?:autonomous-dev-bench|benchmark-core)(?:\s*@|\s*[<>=!~]|\s*$)"
)


def violations(root: Path) -> list[str]:
    findings: list[str] = []
    for path in sorted(root.rglob("*.py")):
        if any(part in {".git", ".venv", "venv", "site-packages"} for part in path.parts):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        except (SyntaxError, UnicodeDecodeError):
            # Intentionally broken corpus fixtures are not production imports.
            # Dependency manifests are checked separately below.
            continue
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for name in names:
                if name.partition(".")[0] in BANNED_IMPORT_ROOTS:
                    findings.append(f"{path}:{node.lineno}: forbidden benchmark import {name}")
    dependency_files = {
        path for pattern in ("pyproject.toml", "setup.cfg", "setup.py", "requirements*.txt", "Pipfile", "uv.lock", "poetry.lock")
        for path in root.rglob(pattern)
        if not any(part in {".git", ".venv", "venv", "site-packages", "node_modules"} for part in path.parts)
    }
    for path in sorted(dependency_files):
        try:
            content = path.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError:
            findings.append(f"{path}: unreadable dependency manifest")
            continue
        if DEPENDENCY_PATTERN.search(content):
            findings.append(f"{path}: forbidden benchmark dependency")
    return findings


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print("usage: check_dependency_firewall.py PRODUCTION_ROOT [...]", file=sys.stderr)
        return 2
    all_findings: list[str] = []
    for value in args:
        root = Path(value).resolve()
        if not root.is_dir():
            all_findings.append(f"{root}: not a directory")
        else:
            all_findings.extend(violations(root))
    if all_findings:
        print("\n".join(all_findings), file=sys.stderr)
        return 1
    print("dependency firewall: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
