"""Execution-engine-neutral workspace operations backed by a Harbor environment."""

from __future__ import annotations

from dataclasses import dataclass
import shlex
from typing import Iterable, Protocol


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

    async def git_diff(self, *, baseline_untracked: Iterable[str] = ()) -> str:
        """Export working-tree changes introduced after the captured workspace baseline."""

        tracked = await self.exec_checked("git diff --binary --no-ext-diff --", cwd=self.repository_root)
        return await self._append_new_untracked(tracked, baseline_untracked=baseline_untracked)

    async def git_diff_since(self, baseline_commit: str, *, baseline_untracked: Iterable[str] = ()) -> str:
        """Export the complete final delta even when an agent commits candidates.

        ADCP's existing ZoneDevelopmentRuntime deliberately commits validated
        candidate snapshots in its isolated worktree. A plain ``git diff`` is
        therefore empty after a clean commit. This method verifies that the
        final HEAD descends from the captured task baseline, then compares that
        baseline commit directly with the final working tree. The same method
        also works for stock agents that leave HEAD unchanged and only edit the
        working tree.
        """

        if not baseline_commit or any(character.isspace() for character in baseline_commit):
            raise ValueError("baseline_commit must be a non-empty Git object id")
        ancestry = await self.environment.exec(
            f"git merge-base --is-ancestor {shlex.quote(baseline_commit)} HEAD",
            cwd=self.repository_root,
        )
        if ancestry.return_code != 0:
            if ancestry.return_code == 1:
                raise RuntimeError("agent changed workspace history outside the captured baseline ancestry")
            stderr = (ancestry.stderr or "")[-2000:]
            raise RuntimeError(f"Harbor workspace ancestry check failed ({ancestry.return_code}): {stderr}")
        tracked = await self.exec_checked(
            f"git diff --binary --no-ext-diff {shlex.quote(baseline_commit)} --",
            cwd=self.repository_root,
        )
        return await self._append_new_untracked(tracked, baseline_untracked=baseline_untracked)

    async def _append_new_untracked(self, tracked: str, *, baseline_untracked: Iterable[str]) -> str:
        baseline = set(baseline_untracked)
        current_untracked = await self.untracked_paths()
        patches = [tracked] if tracked else []
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

    async def git_status(self) -> str:
        return await self.exec_checked("git status --porcelain=v1", cwd=self.repository_root)

    async def repository_head(self) -> str:
        return (await self.exec_checked("git rev-parse HEAD", cwd=self.repository_root)).strip()
