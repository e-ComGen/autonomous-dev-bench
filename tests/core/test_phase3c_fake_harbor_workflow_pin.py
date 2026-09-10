from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "phase3c-adcp-harbor-fake.yml"


def test_fake_harbor_workflow_uses_exact_source_pin_not_pypi_resolution() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "d4509bbd3804f4b408527f476d764dacd988791d" in text
    assert "repository: harbor-framework/harbor" in text
    assert "python -m pip install -e .phase3c-harbor" in text
    assert "harbor-framework==0.22.0" not in text
    assert "HARBOR.lock.json" in text


def test_fake_harbor_workflow_prepares_absolute_task_path_like_host_readiness() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    assert 'cp -a tests/harbor_phase3c_adcp_fake "$TASK"' in text
    assert 'echo "PHASE3C_FAKE_TASK=$TASK" >> "$GITHUB_ENV"' in text
    assert 'harbor trials start -p "$PHASE3C_FAKE_TASK"' in text
    assert "-p scenarios/phase3c/adcp_fake_harbor" not in text
