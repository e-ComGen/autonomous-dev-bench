from __future__ import annotations

import argparse
from hashlib import sha256
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from benchmark_core.deepseek_v4_estimator import (
    DEEPSEEK_V4_MODEL,
    DeepSeekV4RequestEstimator,
)


ROOT = Path(__file__).resolve().parents[1]
LOCK_PATH = ROOT / "DEEPSEEK_V4_ESTIMATOR.lock.json"
DEFAULT_EVIDENCE = ROOT / "artifacts" / "phase3b-deepseek-estimator" / "PHASE3B_DEEPSEEK_V4_ESTIMATOR.json"


def _sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _download_assets(lock: dict[str, object], cache_dir: Path) -> dict[str, Path]:
    from huggingface_hub import hf_hub_download

    source = lock["source"]
    repo_id = source["repo_id"]
    revision = source["revision"]
    files = [
        source["encoding_file"],
        source["encoding_test_file"],
        source["tokenizer_file"],
        source["tokenizer_config_file"],
        *source["golden_cases"],
    ]
    result: dict[str, Path] = {}
    for name in files:
        result[name] = Path(
            hf_hub_download(
                repo_id=repo_id,
                filename=name,
                revision=revision,
                cache_dir=str(cache_dir),
                local_files_only=False,
            )
        )
    return result


def _run_official_encoder_tests(test_script: Path, encoding_file: Path) -> dict[str, object]:
    if not test_script.is_file() or not encoding_file.is_file():
        raise RuntimeError("pinned official encoder test assets are missing after download")

    # Keep the official test script byte-identical. Hugging Face cache paths may
    # resolve individual assets through different symlink/blob locations, so
    # make the pinned encoding module explicitly importable instead of patching
    # the upstream test or assuming one cache-directory layout.
    env = dict(os.environ)
    python_path = [str(encoding_file.parent), str(test_script.parent)]
    existing = env.get("PYTHONPATH")
    if existing:
        python_path.append(existing)
    env["PYTHONPATH"] = os.pathsep.join(python_path)

    execution = subprocess.run(
        [sys.executable, str(test_script)],
        cwd=test_script.parent,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=60,
        check=False,
    )
    if execution.returncode != 0:
        raise RuntimeError(
            "official DeepSeek-V4 encoder tests failed:\n" + execution.stdout[-8000:]
        )
    if "All 4 tests passed!" not in execution.stdout:
        raise RuntimeError("official encoder test process did not report all four passing cases")
    return {
        "return_code": execution.returncode,
        "reported_all_four_passed": True,
        "test_script_sha256": _sha256(test_script),
        "encoding_file_sha256": _sha256(encoding_file),
        "stdout_sha256": sha256(execution.stdout.encode("utf-8")).hexdigest(),
    }


def _wire_case_1(lock: dict[str, object], assets: dict[str, Path], cache_dir: Path) -> dict[str, object]:
    source = lock["source"]
    case = _load_json(assets["encoding/tests/test_input_1.json"])
    if not isinstance(case, dict) or not isinstance(case.get("messages"), list) or not isinstance(case.get("tools"), list):
        raise RuntimeError("official DeepSeek-V4 case 1 has an unexpected shape")

    estimator = DeepSeekV4RequestEstimator.from_huggingface_revision(
        expected_model=DEEPSEEK_V4_MODEL,
        repo_id=source["repo_id"],
        revision=source["revision"],
        cache_dir=cache_dir,
        allow_network=False,
    )
    request = {
        "model": DEEPSEEK_V4_MODEL,
        "messages": case["messages"],
        "tools": case["tools"],
        "thinking": {"type": "enabled"},
        # The official golden test omits reasoning_effort. The pinned encoder's
        # default for the 0731 reference case is the estimator's explicit low
        # policy when thinking is enabled and no effort is supplied.
        "max_tokens": 128,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    rendered = estimator.render_prompt(request)
    gold = assets["encoding/tests/test_output_1.txt"].read_text(encoding="utf-8")
    if rendered != gold:
        raise RuntimeError("wire -> pinned encoder prompt differs from official case 1 golden output")

    estimate = estimator.estimate(request)
    if estimate.input_tokens <= 0:
        raise RuntimeError("pinned tokenizer produced no input tokens")
    if estimate.max_output_tokens != 128:
        raise RuntimeError("wire max_tokens was not preserved in the estimator envelope")

    return {
        "prompt_sha256": sha256(rendered.encode("utf-8")).hexdigest(),
        "golden_prompt_sha256": _sha256(assets["encoding/tests/test_output_1.txt"]),
        "prompt_exact_match": True,
        "input_tokens": estimate.input_tokens,
        "max_output_tokens": estimate.max_output_tokens,
        "max_total_tokens": estimate.max_total_tokens,
        "estimator_identity": {
            "repo_id": estimator.identity.repo_id,
            "revision": estimator.identity.revision,
            "encoding_file": estimator.identity.encoding_file,
            "model": estimator.identity.model,
        },
    }


def _dependency_versions(lock: dict[str, object]) -> dict[str, str]:
    expected = lock["python_dependencies"]
    package_names = {
        "transformers": "transformers",
        "tokenizers": "tokenizers",
        "huggingface-hub": "huggingface-hub",
    }
    actual: dict[str, str] = {}
    for key, distribution in package_names.items():
        version = importlib.metadata.version(distribution)
        if version != expected[key]:
            raise RuntimeError(f"{distribution} version mismatch: expected {expected[key]}, observed {version}")
        actual[key] = version
    return actual


def qualify(evidence_path: Path) -> dict[str, object]:
    lock = _load_json(LOCK_PATH)
    source = lock["source"]
    with tempfile.TemporaryDirectory(prefix="autobench-dsv4-estimator-") as temp:
        cache_dir = Path(temp) / "hf-cache"
        assets = _download_assets(lock, cache_dir)
        official = _run_official_encoder_tests(
            assets[source["encoding_test_file"]],
            assets[source["encoding_file"]],
        )
        wire = _wire_case_1(lock, assets, cache_dir)
        hashes = {name: _sha256(path) for name, path in sorted(assets.items())}

    evidence = {
        "schema_version": 1,
        "scope": "PHASE3B_DEEPSEEK_V4_EXACT_ESTIMATOR_OFFLINE_QUALIFICATION",
        "status": "PASS",
        "model_route": lock["model_route"],
        "source": {
            "repo_id": source["repo_id"],
            "revision": source["revision"],
            "encoding_file": source["encoding_file"],
            "asset_sha256": hashes,
        },
        "dependencies": _dependency_versions(lock),
        "official_encoder_golden_cases": official,
        "wire_adapter_prompt_parity": wire,
        "tokenizer_load": "PASS",
        "provider_usage_source_of_truth": True,
        "live_provider_prompt_usage_parity": False,
        "paid_model_called": False,
        "paid_ready": False,
        "production_blocker": "LIVE_PROVIDER_PROMPT_USAGE_PARITY_NOT_RUN",
    }
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_path.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE)
    args = parser.parse_args()
    evidence = qualify(args.evidence.resolve())
    print(json.dumps(evidence, indent=2, sort_keys=True))
    print(f"DEEPSEEK_V4_ESTIMATOR_OFFLINE_PASS: {args.evidence.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
