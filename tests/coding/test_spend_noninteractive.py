"""Explicit paid automation must not wait for terminal input when credentials are absent."""
from types import SimpleNamespace
import pytest
from suites.coding import spend
from suites.coding.settings import Settings


@pytest.mark.parametrize('value', [None, '', '   '])
@pytest.mark.parametrize('tty', [False, True])
def test_explicit_paid_run_never_prompts_when_key_missing(monkeypatch, value, tty):
    monkeypatch.delenv('DEEPSEEK_API_KEY', raising=False)
    if value is not None:
        monkeypatch.setenv('DEEPSEEK_API_KEY', value)
    monkeypatch.setattr(spend.sys, 'stdin', SimpleNamespace(isatty=lambda: tty))
    def forbidden(*args, **kwargs):
        pytest.fail('Explicit automation must not request terminal input')
    monkeypatch.setattr('builtins.input', forbidden)
    monkeypatch.setattr(spend.getpass, 'getpass', forbidden)
    with pytest.raises(ValueError, match='^DEEPSEEK_API_KEY_MISSING$'):
        spend.authorize(Settings(), 2, True)


def test_paid_authorization_does_not_change_settings_or_print_key(monkeypatch, capsys):
    settings = Settings(requests_per_arm=7, arm_seconds=90)
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'non-secret-test-value')
    assert spend.authorize(settings, 2, True) == 'non-secret-test-value'
    assert settings.requests_per_arm == 7 and settings.arm_seconds == 90
    assert not capsys.readouterr().out
