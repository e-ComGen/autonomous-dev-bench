from __future__ import annotations

import argparse
from copy import deepcopy
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
        source["model_config_file"],
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


def _estimator(lock: dict[str, object], cache_dir: Path) -> DeepSeekV4RequestEstimator:
    source = lock["source"]
    return DeepSeekV4RequestEstimator.from_huggingface_revision(
        expected_model=DEEPSEEK_V4_MODEL,
        repo_id=source["repo_id"],
        revision=source["revision"],
        cache_dir=cache_dir,
        allow_network=False,
    )


def _wire_case_1(lock: dict[str, object], assets: dict[str, Path], cache_dir: Path) -> dict[str, object]:
    case = _load_json(assets["encoding/tests/test_input_1.json"])
    if not isinstance(case, dict) or not isinstance(case.get("messages"), list) or not isinstance(case.get("tools"), list):
        raise RuntimeError("official DeepSeek-V4 case 1 has an unexpected shape")

    estimator = _estimator(lock, cache_dir)
    request = {
        "model": DEEPSEEK_V4_MODEL,
        "messages": case["messages"],
        "tools": case["tools"],
        "thinking": {"type": "enabled"},
        # Official golden case 1 omits reasoning_effort and therefore exercises
        # the pinned reference encoder's own low/no-prefix default.
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


def _live_parity_reference_decomposition(
    lock: dict[str, object], cache_dir: Path
) -> dict[str, object]:
    """Qualify the exact high-vs-low reference prefix for the live probe shape.

    This is entirely offline. It never uses provider usage and never calls a
    model; it proves only what the pinned official encoder/tokenizer themselves
    contribute when the separate reasoning_effort control changes high -> low.
    """
    estimator = _estimator(lock, cache_dir)
    high_request: dict[str, object] = {
        "model": DEEPSEEK_V4_MODEL,
        "messages": [
            {"role": "system", "content": "Answer briefly."},
            {"role": "user", "content": "Reply with OK."},
        ],
        "stream": True,
        "stream_options": {"include_usage": True},
        "thinking": {"type": "enabled"},
        "reasoning_effort": "high",
        "max_tokens": 8,
    }
    low_request = deepcopy(high_request)
    low_request["reasoning_effort"] = "low"
    high = estimator.estimate(high_request)
    low = estimator.estimate(low_request)
    prefix_tokens = high.input_tokens - low.input_tokens
    if low.input_tokens <= 0:
        raise RuntimeError("live parity low/no-prefix reference produced no input tokens")
    if prefix_tokens <= 0:
        raise RuntimeError("pinned high reasoning-effort reference prefix is not token-positive")
    return {
        "request_identity": {
            "model": DEEPSEEK_V4_MODEL,
            "system": "Answer briefly.",
            "user": "Reply with OK.",
            "thinking": "enabled",
            "reasoning_effort": "high",
            "max_tokens": 8,
        },
        "high_reference_input_tokens": high.input_tokens,
        "low_no_prefix_input_tokens": low.input_tokens,
        "high_effort_prefix_tokens": prefix_tokens,
        "paid_model_called": False,
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
        live_probe_reference = _live_parity_reference_decomposition(lock, cache_dir)
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
        "live_probe_reference_decomposition": live_probe_reference,
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
