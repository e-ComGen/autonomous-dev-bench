import asyncio
from dataclasses import dataclass

import pytest

from suites.coding.harbor.workspace import HarborWorkspaceFacade


@dataclass
class FakeResult:
    stdout: str | None = ""
    stderr: str | None = ""
    return_code: int = 0


class FakeEnvironment:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def exec(self, command, **kwargs):
        self.calls.append((command, kwargs))
        return self.responses.pop(0)


def test_workspace_facade_uses_repository_root_and_returns_git_evidence():
    environment = FakeEnvironment([
        FakeResult(stdout="abc123\n"),
        FakeResult(stdout=" M message.txt\n"),
        FakeResult(stdout="diff --git a/message.txt b/message.txt\n"),
        FakeResult(stdout=""),
    ])
    workspace = HarborWorkspaceFacade(environment, "/repo")

    async def exercise():
        assert await workspace.repository_head() == "abc123"
        assert "message.txt" in await workspace.git_status()
        assert (await workspace.git_diff()).startswith("diff --git")

    asyncio.run(exercise())
    assert all(call[1]["cwd"] == "/repo" for call in environment.calls)


def test_workspace_facade_exports_untracked_files_without_staging_them():
    environment = FakeEnvironment([
        FakeResult(stdout=""),
        FakeResult(stdout="new file.txt\0binary.dat\0"),
        FakeResult(stdout="diff --git a/new file.txt b/new file.txt\nnew file mode 100644\n", return_code=1),
        FakeResult(stdout="diff --git a/binary.dat b/binary.dat\nnew file mode 100644\n", return_code=1),
    ])
    workspace = HarborWorkspaceFacade(environment, "/repo")

    patch = asyncio.run(workspace.git_diff())

    assert "new file.txt" in patch
    assert "binary.dat" in patch
    assert "git add" not in "\n".join(call[0] for call in environment.calls)
    assert any("'new file.txt'" in call[0] for call in environment.calls)


def test_workspace_facade_exports_committed_candidate_from_exact_baseline():
    baseline = "a" * 40
    environment = FakeEnvironment([
        FakeResult(stdout="diff --git a/source.py b/source.py\n+candidate\n"),
        FakeResult(stdout=""),
    ])
    workspace = HarborWorkspaceFacade(environment, "/repo")

    patch = asyncio.run(workspace.git_diff_from(baseline))

    assert "+candidate" in patch
    assert environment.calls[0][0] == f"git diff --binary --no-ext-diff {baseline} --"
    assert all(call[1]["cwd"] == "/repo" for call in environment.calls)


def test_workspace_facade_rejects_noncanonical_baseline_before_execution():
    environment = FakeEnvironment([])
    workspace = HarborWorkspaceFacade(environment)

    with pytest.raises(ValueError, match="exact lowercase SHA-1"):
        asyncio.run(workspace.git_diff_from("HEAD~1"))
    assert not environment.calls


def test_workspace_facade_fails_closed_on_nonzero_command():
    environment = FakeEnvironment([FakeResult(stderr="denied", return_code=7)])
    workspace = HarborWorkspaceFacade(environment)

    with pytest.raises(RuntimeError, match="Harbor workspace command failed"):
        asyncio.run(workspace.git_diff())
