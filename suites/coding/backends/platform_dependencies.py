"""Explicit native compatibility dependencies inferred from pre-fix imports only."""
import ast
import sys
from corpus.qualification.files import text

POLICY_VERSION = "native-build/v2-sdist-windows-curses"


def compatibility_dependencies(files, platform=None):
    if (platform or sys.platform) != "win32":
        return ()
    for path, record in files.items():
        if not path.endswith(".py"):
            continue
        try:
            tree = ast.parse(text(record), filename=path)
        except (SyntaxError, UnicodeError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules = (alias.name.split('.')[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                modules = ((node.module or "").split('.')[0],)
            else:
                continue
            if any(module in {"curses", "_curses"} for module in modules):
                return ("windows-curses==2.4.2",)
    return ()
