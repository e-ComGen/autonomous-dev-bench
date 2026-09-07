"""One-click composition: qualify, freeze, execute stock/cycle, independently score."""
from dataclasses import asdict
from pathlib import Path
import getpass
import json
import os
import secrets
import sys
import tempfile

from benchmark_core.identity import canonical_json
from cli.oneclick.catalog import read_catalog
from .adcp_loading import load_adcp
from .docker_runtime import DockerRuntime
from .evaluation import Evaluator
from .experiment import run_episode, schedule, with_usage
from .native import NativeDriver
from .selection import candidate_order, selection_digest
from .settings import load_settings
from .source import project_source


def authorize(settings, episodes, allowed):
    if not allowed:
        if not sys.stdin.isatty():
            raise ValueError("Paid requests require --allow-live-model in noninteractive runs")
        print(f"Run {episodes} paid episodes? Each arm: at most {settings.requests_per_arm} provider requests, "
              f"{settings.output_tokens_per_request} output tokens/request, {settings.arm_seconds}s.")
        print("These are request/time caps, NOT a hard dollar limit.")
        if input("Type YES to run both arms: ").strip() != "YES":
            raise ValueError("MODEL_SPEND_NOT_AUTHORIZED")
    key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not key and sys.stdin.isatty():
        key = getpass.getpass("DeepSeek API key (not saved): ").strip()
    if not key:
        raise ValueError("DEEPSEEK_API_KEY_MISSING")
    return key


def run_ab(root, arguments, report):
    if arguments.offline:
        raise ValueError("A/B needs a real provider; --offline never substitutes self-tests")
    if sys.version_info < (3, 12):
        raise ValueError("Real ADCP A/B requires Python 3.12 or newer")
    settings = load_settings(Path(arguments.ab_config).resolve())
    seed = arguments.seed if arguments.seed is not None else secrets.randbits(64)
    ordered = candidate_order(settings.projects, seed)
    identity = load_adcp(root)
    root = Path(root)
    parent = os.environ.get("AUTOBENCH_TEST_TMPDIR") or tempfile.gettempdir()
    result = {"status": "PREPARING", "seed": seed, "settings": asdict(settings), "adcp": identity,
              "task_source": "REAL_SOURCE_FUNCTION_RECONSTRUCTION", "scope": "PYTHON_PACKAGE_PROJECTION",
              "live_model_called": False, "rows": [], "rejections": [], "qualified_tasks": []}
    with tempfile.TemporaryDirectory(prefix="ab-", dir=parent) as temporary:
        scratch = Path(temporary)
        docker = DockerRuntime(root, scratch, settings)
        provider_path = None
        try:
            result["image"] = docker.prepare_image()
            evaluator = Evaluator(docker, root, scratch / "checks", settings.check_seconds)
            catalog = {entry.project_id: entry for entry in read_catalog(root)}
            prepared = []
            references = {}
            for recipe in ordered:
                try:
                    if recipe.project_id not in references:
                        references[recipe.project_id] = project_source(root, catalog[recipe.project_id], recipe,
                            scratch / recipe.project_id, network=arguments.allow_network)
                    data = evaluator.qualify(recipe, references[recipe.project_id])
                    prepared.append((recipe, data))
                    entry = catalog[recipe.project_id]
                    result["qualified_tasks"].append({"task": recipe.task_id, "project": recipe.project_id,
                        "commit": entry.commit, "source_digest": entry.source_digest, **data["qualification"]})
                    print(f"Selected: {recipe.project_id} / {recipe.task_id}; seed={seed}", flush=True)
                    if len(prepared) == settings.tasks:
                        break
                except (OSError, ValueError, RuntimeError) as error:
                    result["rejections"].append({"task": recipe.task_id, "reason": str(error)[:1000]})
            if len(prepared) != settings.tasks:
                raise RuntimeError("QUALIFIED_TASK_QUOTA_NOT_MET")
            result["selection_digest"] = selection_digest([recipe for recipe, _ in prepared], settings)
            boot = NativeDriver(docker, scratch / "boot", settings, "no-provider")
            boot.invoke(prepared[0][1]["files"], "", boot_only=True)
            result["native_boot"] = "BOOTED"
            if arguments.command == "ab-preflight":
                result["status"] = "READY_FOR_AB"
                return result
            scheduled = schedule(prepared, settings.repeats, seed)
            result["enrolled_episodes"] = len(scheduled)
            result["order"] = [{"task": recipe.task_id, "repetition": repetition, "arm": arm}
                               for recipe, _, repetition, arm in scheduled]
            key = authorize(settings, len(scheduled), arguments.allow_live_model)
            tokens = {secrets.token_hex(24): recipe.task_id + f":{repetition}:{arm}"
                      for recipe, _, repetition, arm in scheduled}
            inverse = {value: key for key, value in tokens.items()}
            previous_key = os.environ.get("DEEPSEEK_API_KEY")
            try:
                os.environ["DEEPSEEK_API_KEY"] = key
                provider_path = docker.start_relay(tokens)
            finally:
                if previous_key is None:
                    os.environ.pop("DEEPSEEK_API_KEY", None)
                else:
                    os.environ["DEEPSEEK_API_KEY"] = previous_key
                key = None
            result["status"] = "RUNNING"
            report.save(result)
            for recipe, data, repetition, arm in scheduled:
                token = inverse[recipe.task_id + f":{repetition}:{arm}"]
                row = run_episode(root, recipe, data, repetition, arm, docker, evaluator, token,
                                  settings, report, scratch)
                result["rows"].append(row)
                result["rows"] = with_usage(result["rows"], provider_path)
                result["live_model_called"] = any(row["usage"]["model_requests"] for row in result["rows"])
                print(f"{arm}: {row['external_verdict']}; delivered={row['delivered']}; {row['wall_seconds']}s", flush=True)
                report.save(result)
            result["status"] = "AB_COMPLETE"
            result["comparison"] = {arm: {"episodes": sum(row["arm"] == arm for row in result["rows"]),
                "solved": sum(row["solved"] for row in result["rows"] if row["arm"] == arm),
                "external_pass": sum(row["external_pass"] for row in result["rows"] if row["arm"] == arm)}
                for arm in ("stock", "cycle")}
        except KeyboardInterrupt:
            result["status"] = "CANCELLED"
        except (OSError, ValueError, RuntimeError) as error:
            result.update(status="AB_INCOMPLETE", reason=str(error)[:1500])
        finally:
            if provider_path and provider_path.is_file():
                raw = provider_path.read_text(encoding="utf-8")
                result["provider_receipt"] = report.cas.put_text(raw)
                result["live_model_called"] = any(state["admitted"] for state in json.loads(raw).values())
            logs = {str(path.relative_to(scratch)): path.read_text(encoding="utf-8", errors="replace")[-65536:]
                    for path in scratch.rglob("process.log")}
            build_log = scratch / "image-build.log"
            if build_log.is_file():
                logs["image-build.log"] = build_log.read_text()[-65536:]
            result["diagnostics_ref"] = report.cas.put_text(canonical_json(logs))
            docker.close()
    return result
