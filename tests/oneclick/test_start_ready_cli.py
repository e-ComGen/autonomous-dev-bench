"""Exercise the real launcher process without contacting GitHub or a paid provider."""
from pathlib import Path
import json
import os
import shutil
import subprocess
import sys
import pytest

ROOT = Path(__file__).resolve().parents[2]


def copy_entrypoint(tmp_path):
    root = tmp_path / "folder with spaces"
    tools = root / "tools"
    tools.mkdir(parents=True)
    for name in ("start_ready.py", "launcher_credentials.py"):
        shutil.copyfile(ROOT / "tools" / name, tools / name)
    shutil.copyfile(ROOT / "START.cmd", root / "START.cmd")
    return root


def invoke(root, env, *args):
    if os.name == "nt":
        command = [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/c", "START.cmd", *args]
    else:
        command = [sys.executable, "-I", "tools/start_ready.py", *args]
    return subprocess.run(command, cwd=root, env=env, stdin=subprocess.DEVNULL,
                          capture_output=True, text=True, timeout=15, shell=False)


def test_real_batch_does_not_prompt_and_passes_credentials_only_in_environment(tmp_path):
    root = copy_entrypoint(tmp_path)
    (root / ".env").write_text("GITHUB_TOKEN=not-a-real-github-token\nDEEPSEEK_API_KEY=not-a-real-model-key\nAUTOBENCH_ALLOW_PAID=YES\n")
    (root / "tools/prepare_ab.py").write_text("def prepare_runtime():\n    pass  # TEST BOUNDARY: no private source acquisition\n")
    (root / "tools/launch.py").write_text(
        "import json,os,sys\nfrom pathlib import Path\n"
        "Path('observed.json').write_text(json.dumps({'argv':sys.argv[1:],'github':bool(os.environ.get('GITHUB_TOKEN')),"
        "'model':bool(os.environ.get('DEEPSEEK_API_KEY'))}))\nraise SystemExit(7)\n")
    environment = {key: value for key, value in os.environ.items()
                   if key not in {"GITHUB_TOKEN", "GH_TOKEN", "DEEPSEEK_API_KEY", "AUTOBENCH_ALLOW_PAID"}}
    result = invoke(root, environment)
    assert result.returncode == 7, result.stdout + result.stderr
    observed = json.loads((root / "observed.json").read_text())
    assert observed["github"] and observed["model"]
    assert observed["argv"] == ["ab", "--allow-live-model", "--allow-local-execution"]
    assert "not-a-real-" not in result.stdout + result.stderr
    assert "Type YES" not in result.stdout and "[Y/N]" not in result.stdout


def test_real_missing_key_path_ends_without_hanging_on_stdin(tmp_path):
    root = copy_entrypoint(tmp_path)
    environment = {key: value for key, value in os.environ.items()
                   if key not in {"GITHUB_TOKEN", "GH_TOKEN", "DEEPSEEK_API_KEY", "AUTOBENCH_ALLOW_PAID"}}
    result = invoke(root, environment)
    assert result.returncode == 2, result.stdout + result.stderr
    assert "GITHUB_TOKEN" in result.stderr and ".env" in result.stderr
    assert (root / ".env").is_file()
    assert not (root / "observed.json").exists()
