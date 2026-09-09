from pathlib import Path

import pytest

from benchmark_core.cas import FileSystemCAS
from suites.coding.harbor.cas_export import export_harbor_trial_to_cas


def make_trial(root: Path, *, secret: str | None = None) -> Path:
    trial = root / "trial"
    (trial / "agent").mkdir(parents=True)
    (trial / "result.json").write_text('{"status":"ok"}\n', encoding="utf-8")
    (trial / "agent" / "PATCH.diff").write_text("diff --git a/a b/a\n", encoding="utf-8")
    (trial / "trial.log").write_text(f"log {secret or 'clean'}\n", encoding="utf-8")
    return trial


def test_harbor_trial_export_is_content_addressed_and_host_path_independent(tmp_path):
    cas = FileSystemCAS(tmp_path / "cas")
    first = make_trial(tmp_path / "one")
    second = make_trial(tmp_path / "two")

    exported_first = export_harbor_trial_to_cas(first, cas, provenance={"harbor_commit": "abc"})
    exported_second = export_harbor_trial_to_cas(second, cas, provenance={"harbor_commit": "abc"})

    assert exported_first.manifest_ref == exported_second.manifest_ref
    assert exported_first.manifest["result_ref"].startswith("cas:sha256:")
    assert exported_first.manifest["patch_ref"].startswith("cas:sha256:")
    assert cas.verify(exported_first.manifest_ref)
    for entry in exported_first.manifest["files"]:
        assert cas.verify(entry["ref"])


def test_harbor_trial_export_scans_for_secrets_before_writing_cas(tmp_path):
    cas = FileSystemCAS(tmp_path / "cas")
    trial = make_trial(tmp_path / "source", secret="do-not-export")

    with pytest.raises(ValueError, match="forbidden secret material"):
        export_harbor_trial_to_cas(trial, cas, forbidden_values=["do-not-export"])

    assert not list((tmp_path / "cas" / "sha256").rglob("*"))
