import asyncio
from dataclasses import dataclass

import pytest

from suites.coding.harbor.workspace import HarborWorkspaceFacade


@dataclass
class Result:
    stdout: str = ""
    stderr: str = ""
    return_code: int = 0


class FakeEnvironment:
    def __init__(self):
        self.current_untracked = ("generated/preexisting.txt",)
        self.commands = []
        self.tracked_dirty = False

    async def exec(self, command, **kwargs):
        self.commands.append((command, kwargs.get("cwd")))
        if command == "git diff --quiet --no-ext-diff --":
            return Result(return_code=1 if self.tracked_dirty else 0)
        if command == "git diff --binary --no-ext-diff --":
            return Result(stdout="")
        if command == "git ls-files --others --exclude-standard -z":
            return Result(stdout="\0".join(self.current_untracked) + "\0")
        if command.startswith("git diff --binary --no-index -- /dev/null "):
            path = command.rsplit(" ", 1)[-1]
            return Result(
                stdout=(
                    f"diff --git a/{path} b/{path}\n"
                    "new file mode 100644\n"
                    "--- /dev/null\n"
                    f"+++ b/{path}\n"
                    "@@ -0,0 +1 @@\n"
                    "+new\n"
                ),
                return_code=1,
            )
        raise AssertionError(f"unexpected command: {command}")


def test_patch_export_excludes_preexisting_untracked_paths():
    environment = FakeEnvironment()
    workspace = HarborWorkspaceFacade(environment)

    baseline = asyncio.run(workspace.untracked_paths())
    environment.current_untracked = ("generated/preexisting.txt", "agent-created.txt")
    patch = asyncio.run(workspace.git_diff(baseline_untracked=baseline))

    assert "agent-created.txt" in patch
    assert "generated/preexisting.txt" not in patch
    diff_commands = [command for command, _ in environment.commands if "--no-index" in command]
    assert len(diff_commands) == 1
    assert "agent-created.txt" in diff_commands[0]


def test_dirty_tracked_baseline_is_rejected():
    environment = FakeEnvironment()
    environment.tracked_dirty = True
    workspace = HarborWorkspaceFacade(environment)

    with pytest.raises(RuntimeError, match="tracked baseline is dirty"):
        asyncio.run(workspace.require_clean_tracked_baseline())
