"""Execution-engine-neutral workspace operations backed by a Harbor environment."""

from __future__ import annotations

from dataclasses import dataclass
import re
import shlex
from typing import Iterable, Protocol


_COMMIT_RE = re.compile(r"[0-9a-f]{40}")


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

    async def untracked_paths(self) -> tuple[str, ...]:
        """Return the current untracked workspace paths in a deterministic order."""
        output = await self.exec_checked(
            "git ls-files --others --exclude-standard -z",
            cwd=self.repository_root,
        )
        return tuple(sorted(item for item in output.split("\0") if item))

    async def require_clean_tracked_baseline(self) -> None:
        """Reject a task environment whose tracked tree is already modified before the agent runs."""
        result = await self.environment.exec(
            "git diff --quiet --no-ext-diff --",
            cwd=self.repository_root,
        )
        if result.return_code == 0:
            return
        if result.return_code == 1:
            raise RuntimeError("Harbor workspace tracked baseline is dirty before agent execution")
        stderr = (result.stderr or "")[-2000:]
        raise RuntimeError(f"Harbor workspace baseline check failed ({result.return_code}): {stderr}")

    async def _untracked_patch(self, baseline_untracked: Iterable[str]) -> str:
        baseline = set(baseline_untracked)
        current_untracked = await self.untracked_paths()
        patches: list[str] = []
        for path in (path for path in current_untracked if path not in baseline):
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

    async def git_diff(self, *, baseline_untracked: Iterable[str] = ()) -> str:
        """Export uncommitted tracked changes plus newly-created untracked files."""
        tracked = await self.exec_checked("git diff --binary --no-ext-diff --", cwd=self.repository_root)
        return tracked + await self._untracked_patch(baseline_untracked)

    async def git_diff_from(self, baseline_commit: str, *, baseline_untracked: Iterable[str] = ()) -> str:
        """Export the complete candidate patch even when the agent committed it.

        ``git diff <baseline> --`` compares the immutable pre-agent commit with
        the current working tree, so committed ADCP candidate snapshots and any
        later uncommitted tracked edits are both represented exactly once.
        """
        if not isinstance(baseline_commit, str) or _COMMIT_RE.fullmatch(baseline_commit) is None:
            raise ValueError("baseline_commit must be an exact lowercase SHA-1 commit")
        tracked = await self.exec_checked(
            f"git diff --binary --no-ext-diff {baseline_commit} --",
            cwd=self.repository_root,
        )
        return tracked + await self._untracked_patch(baseline_untracked)

    async def git_status(self) -> str:
        return await self.exec_checked("git status --porcelain=v1", cwd=self.repository_root)

    async def repository_head(self) -> str:
        return (await self.exec_checked("git rev-parse HEAD", cwd=self.repository_root)).strip()
