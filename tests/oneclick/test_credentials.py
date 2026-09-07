from pathlib import Path
import json
import os
import subprocess
import sys
import pytest
from tools.launcher_credentials import (
    KEYS, parse_credentials, read_credentials, create_template, host_credentials, paid_authorized,
)
from tools.launch import host_environment
from tools.launcher_env import clean_environment
from tools.start_ready import configured_arguments, ConfigurationRequired, main


@pytest.fixture(autouse=True)
def without_real_keys(monkeypatch):
    for key in KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr("builtins.input", lambda *args: pytest.fail("Unexpected interactive question"))
    monkeypatch.setattr("getpass.getpass", lambda *args: pytest.fail("Unexpected credential question"))


def configured(root):
    (root / ".env").write_text("GITHUB_TOKEN=unit-github\nDEEPSEEK_API_KEY=unit-deepseek\nAUTOBENCH_ALLOW_PAID=YES\n")
    return read_credentials(root)


@pytest.mark.parametrize("value", ["YES", "yes", "Yes", "1", "on", "true", " YES "])
def test_persisted_paid_optin_is_explicit_case_insensitive(value):
    assert paid_authorized(value)


@pytest.mark.parametrize("value", ["", "NO", "false", "0", "maybe", "yesterday"])
def test_missing_or_negative_value_does_not_authorize_paid_requests(value):
    assert not paid_authorized(value)


def test_parser_preserves_literal_values_and_accepts_bom_quotes():
    parsed = parse_credentials('\ufeff# keys\nexport GH_TOKEN="unit-github"\nDEEPSEEK_API_KEY=\'literal$token\'\nOTHER=ignored\n')
    assert parsed == {"GH_TOKEN": "unit-github", "DEEPSEEK_API_KEY": "literal$token"}


@pytest.mark.parametrize("content", ["GITHUB_TOKEN=first\nGITHUB_TOKEN=second", 'GITHUB_TOKEN="unclosed',
                                     "GITHUB_TOKEN=bad value", "GITHUB_TOKEN=secret\x00value"])
def test_bad_credentials_fail_without_echoing_values(content):
    with pytest.raises(ValueError) as exception:
        parse_credentials(content)
    assert "first" not in str(exception.value) and "secret" not in str(exception.value)


def test_environment_alias_precedes_file_and_blank_environment_does_not(tmp_path):
    configured(tmp_path)
    assert read_credentials(tmp_path, {"GH_TOKEN": "env-alias"})["GITHUB_TOKEN"] == "env-alias"
    assert read_credentials(tmp_path, {"GITHUB_TOKEN": " "})["GITHUB_TOKEN"] == "unit-github"


def test_template_is_never_written_over_real_keys(tmp_path):
    values = configured(tmp_path)
    original = (tmp_path / ".env").read_bytes()
    create_template(tmp_path)
    assert (tmp_path / ".env").read_bytes() == original
    assert read_credentials(tmp_path) == values


def test_authorized_launch_adds_real_flags_once_without_input(tmp_path):
    values = configured(tmp_path)
    arguments = configured_arguments(tmp_path, [], values)
    assert arguments == ["ab", "--allow-live-model", "--allow-local-execution"]
    assert configured_arguments(tmp_path, arguments, values) == arguments
    assert all("unit-" not in argument for argument in arguments)


def test_local_execution_does_not_implicitly_authorize_payment(tmp_path):
    values = configured(tmp_path)
    values["AUTOBENCH_ALLOW_PAID"] = "NO"
    with pytest.raises(ConfigurationRequired, match="AUTOBENCH_ALLOW_PAID"):
        configured_arguments(tmp_path, ["ab", "--allow-local-execution"], values)


def test_qualification_requires_no_model_key_or_payment(tmp_path):
    arguments = configured_arguments(tmp_path, ["qualify"], {"GITHUB_TOKEN": "unit-gh"})
    assert arguments == ["qualify", "--allow-local-execution"]


def test_missing_token_fails_before_bootstrap_and_never_prompts(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("subprocess.call", lambda *args, **kwargs: pytest.fail("Must not bootstrap"))
    assert main(["ab"], root=tmp_path) == 2
    assert (tmp_path / ".env").is_file()
    assert "GITHUB_TOKEN" in capsys.readouterr().err
    assert json.loads((tmp_path / ".bench/startup.json").read_text())["status"] == "CONFIG_REQUIRED"


def test_replay_with_staged_adcp_needs_no_github_key(tmp_path):
    path = tmp_path / ".bench/adcp/SOURCE.json"
    path.parent.mkdir(parents=True)
    path.write_text("{}")
    values = {"GITHUB_TOKEN": "", "DEEPSEEK_API_KEY": "unit-key", "AUTOBENCH_ALLOW_PAID": "YES"}
    assert "--allow-live-model" in configured_arguments(tmp_path, ["ab", "--replay=x.json"], values)


def test_host_environment_delivers_keys_to_real_subprocess_not_bootstrap(tmp_path):
    configured(tmp_path)
    host = host_environment(tmp_path, "ab")
    probe = subprocess.run([sys.executable, "-I", "-c",
        "import os,json; print(json.dumps({k:bool(os.environ.get(k)) for k in ['GITHUB_TOKEN','GH_TOKEN','DEEPSEEK_API_KEY']}))"],
        env=host, capture_output=True, text=True, timeout=10, check=True)
    assert json.loads(probe.stdout) == {"GITHUB_TOKEN": True, "GH_TOKEN": True, "DEEPSEEK_API_KEY": True}
    assert not any(key in clean_environment(tmp_path) for key in KEYS)
    assert not any(key in host_environment(tmp_path, "test") for key in KEYS)
    assert "DEEPSEEK_API_KEY" not in host_environment(tmp_path, "qualify")


def test_secret_environment_restored_after_failure(tmp_path, monkeypatch):
    values = configured(tmp_path)
    monkeypatch.setenv("GITHUB_TOKEN", "old-value")
    with pytest.raises(RuntimeError):
        with host_credentials(values):
            assert os.environ["GITHUB_TOKEN"] == "unit-github"
            raise RuntimeError("stop")
    assert os.environ["GITHUB_TOKEN"] == "old-value"
    assert "DEEPSEEK_API_KEY" not in os.environ


def test_actual_main_dispatch_is_noninteractive_and_preserves_host_keys(tmp_path, monkeypatch):
    configured(tmp_path)
    seen = []
    def dispatch(argv, **kwargs):
        assert os.environ["GITHUB_TOKEN"] == "unit-github"
        assert kwargs["stdin"] == subprocess.DEVNULL
        assert "--allow-local-execution" in argv
        seen.append(argv)
        return 0
    monkeypatch.setattr("subprocess.call", dispatch)
    assert main(["qualify", "--backend", "native"], root=tmp_path) == 0
    assert len(seen) == 1
    assert "GITHUB_TOKEN" not in os.environ


def test_help_and_offline_test_do_not_read_private_dotenv(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("GITHUB_TOKEN=secret with spaces")
    monkeypatch.setattr("subprocess.call", lambda *args, **kwargs: 0)
    assert main(["test", "--offline"], root=tmp_path) == 0
    assert main(["--help"], root=tmp_path) == 0


def test_batch_entrypoints_have_no_confirmation_or_pause():
    root = Path(__file__).resolve().parents[2]
    for name in ("START.cmd", "RUN_NATIVE_ONCE.cmd"):
        text = (root / name).read_text().lower()
        assert "choice" not in text and "set /p" not in text and "pause" not in text
    assert "start_ready.py" in (root / "START.cmd").read_text()
