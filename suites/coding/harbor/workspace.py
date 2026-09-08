"""Execution-engine-neutral workspace operations backed by a Harbor environment."""

from __future__ import annotations

from dataclasses import dataclass
import shlex
from typing import Protocol


class ExecResultLike(Protocol):
    stdout: str | None
    stderr: str | None
    return_code: int


class EnvironmentLike(Protocol):
    async def exec(self, command: str, **kwargs) -> ExecResultLike: ...


@dataclass(slots=True)
class HarborWorkspaceFacade:
    environment: EnvironmentLike
    repository_root: str = "/workspace"

    async def exec_checked(self, command: str, *, cwd: str | None = None) -> str:
        result = await self.environment.exec(command, cwd=cwd or self.repository_root)
        if result.return_code != 0:
            stderr = (result.stderr or "")[-2000:]
            raise RuntimeError(f"Harbor workspace command failed ({result.return_code}): {stderr}")
        return result.stdout or ""

    async def git_diff(self) -> str:
        """Export tracked and untracked repository changes without mutating the index."""

        tracked = await self.exec_checked("git diff --binary --no-ext-diff --", cwd=self.repository_root)
        untracked_output = await self.exec_checked(
            "git ls-files --others --exclude-standard -z",
            cwd=self.repository_root,
        )
        patches = [tracked] if tracked else []
        for path in (item for item in untracked_output.split("\0") if item):
            result = await self.environment.exec(
                f"git diff --binary --no-index -- /dev/null {shlex.quote(path)}",
                cwd=self.repository_root,
            )
            if result.return_code not in (0, 1):
                stderr = (result.stderr or "")[-2000:]
                raise RuntimeError(f"Harbor untracked diff failed ({result.return_code}) for {path!r}: {stderr}")
            if result.stdout:
                patches.append(result.stdout)
        return "".join(patches)

    async def git_status(self) -> str:
        return await self.exec_checked("git status --porcelain=v1", cwd=self.repository_root)

    async def repository_head(self) -> str:
        return (await self.exec_checked("git rev-parse HEAD", cwd=self.repository_root)).strip()
