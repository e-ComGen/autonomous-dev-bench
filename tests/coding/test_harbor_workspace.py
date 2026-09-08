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
    ])
    workspace = HarborWorkspaceFacade(environment, "/repo")

    async def exercise():
        assert await workspace.repository_head() == "abc123"
        assert "message.txt" in await workspace.git_status()
        assert (await workspace.git_diff()).startswith("diff --git")

    asyncio.run(exercise())
    assert all(call[1]["cwd"] == "/repo" for call in environment.calls)


def test_workspace_facade_fails_closed_on_nonzero_command():
    environment = FakeEnvironment([FakeResult(stderr="denied", return_code=7)])
    workspace = HarborWorkspaceFacade(environment)

    with pytest.raises(RuntimeError, match="Harbor workspace command failed"):
        asyncio.run(workspace.git_diff())
