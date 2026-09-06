from pathlib import Path
import subprocess
import sys


def write_artifact(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def child_value() -> str:
    result = subprocess.run(
        [sys.executable, "-c", "print('child-ok')"],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def crash_point() -> None:
    raise RuntimeError("controlled self-test crash point")
