"""Cross-platform replay script generation."""
from __future__ import annotations

import os
from pathlib import Path
import shlex
import subprocess
from typing import Mapping, Sequence


def _bat_quote(value: str) -> str:
    return subprocess.list2cmdline([value])


def write_replay_scripts(directory: str | os.PathLike[str], argv: Sequence[str], *, environment: Mapping[str, str] | None = None,
                         working_directory: str = ".") -> tuple[Path, Path]:
    if not argv: raise ValueError("replay argv cannot be empty")
    root = Path(directory); root.mkdir(parents=True, exist_ok=True); env = dict(sorted((environment or {}).items()))
    sh_lines = ["#!/bin/sh", "set -eu", f"cd {shlex.quote(working_directory)}"]
    sh_lines.extend(f"export {name}={shlex.quote(value)}" for name, value in env.items())
    sh_lines.append("exec " + shlex.join(list(argv)))
    bat_lines = ["@echo off", "setlocal", f"cd /d {_bat_quote(working_directory)}"]
    bat_lines.extend(f'set "{name}={value}"' for name, value in env.items())
    bat_lines.append("call " + subprocess.list2cmdline(list(argv)))
    bat_lines.append("exit /b %ERRORLEVEL%")
    sh = root / "replay.sh"; bat = root / "replay.bat"
    sh.write_text("\n".join(sh_lines) + "\n", encoding="utf-8", newline="\n")
    bat.write_text("\r\n".join(bat_lines) + "\r\n", encoding="utf-8", newline="")
    try: sh.chmod(sh.stat().st_mode | 0o111)
    except OSError: pass
    return sh, bat
