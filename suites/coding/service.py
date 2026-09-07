"""End-to-end real GitHub issue A/B; never substitute infrastructure self-tests."""
from dataclasses import asdict
from pathlib import Path
import os
import secrets
import sys
import tempfile
from benchmark_core.identity import canonical_json
from .settings import load_campaign
from .docker_runtime import DockerRuntime
from .adcp_loading import load_adcp
from .native import NativeDriver
from .issue_preparation import prepare, save_lock, restore_lock
from .issue_campaign import run_pairs
from corpus.qualification.workspace import RepositoryWorkspace


def run_ab(root, arguments, report):
    if arguments.offline:
        raise ValueError("The real issue A/B path needs network access; it never substitutes artificial tasks")
    if sys.version_info < (3, 12):
        raise ValueError("Python 3.12 or newer is required")
    settings, policy = load_campaign(Path(arguments.ab_config).resolve())
    if settings.task_source != "github_issue":
        raise ValueError("A/B uses real issues; reconstruction is only an infrastructure fixture")
    seed = arguments.seed if arguments.seed is not None else secrets.randbits(64)
    if not 0 <= seed < 2**64:
        raise ValueError("Seed must be an unsigned 64-bit integer")
    only_qualify = arguments.command == "qualify"
    identity = None if only_qualify else load_adcp(root)
    result = {"status": "PREPARING", "seed": seed, "settings": asdict(settings), "adcp": identity,
              "task_source": "GITHUB_ISSUE_MERGED_PR", "workspace": "FULL_REPOSITORY",
              "adcp_view": "ALL_EDITABLE_PYTHON_SOURCE", "live_model_called": False, "rows": []}
    parent = os.environ.get("AUTOBENCH_TEST_TMPDIR") or tempfile.gettempdir()
    with tempfile.TemporaryDirectory(prefix="ab-", dir=parent) as temporary:
        docker = DockerRuntime(root, Path(temporary), settings)
        try:
            result["image"] = docker.prepare_image()
            base_image = docker.image
            replay = getattr(arguments, "replay", None)
            if replay:
                seed, prepared = restore_lock(replay, root, docker, report, settings, policy)
                result["seed"] = seed
            else:
                prepared = prepare(root, docker, report, settings, policy, seed)
            result["selection_lock"] = save_lock(report, seed, settings, policy, prepared)
            result["qualified_tasks"] = [{"task": task.task_id, "repository": task.project_id,
                "issue": data["captured"]["candidate"]["issues"][0]["number"],
                "base_commit": data["captured"]["candidate"]["pre_fix_commit"],
                "reference_commit": data["captured"]["candidate"]["reference_commit"],
                "classification": data["captured"]["classification"],
                "fail_to_pass_count": len(data["qualification"]["fail_to_pass"]),
                "pass_to_pass_count": len(data["qualification"]["pass_to_pass"])} for task, data in prepared]
            if only_qualify:
                result["status"] = "TASKS_QUALIFIED"
            else:
                from .cycle import preflight_cycle
                result["cycle_preflight"] = []
                for task, data in prepared:
                    driver = NativeDriver(docker, docker.scratch / (task.task_id + "-preflight-native"), settings, "no-dispatch")
                    checked = preflight_cycle(driver, data["evaluator"], data["files"], task,
                        data["public_checks"], data["public_expected"], docker.scratch / (task.task_id + "-preflight"), settings)
                    result["cycle_preflight"].append({"task": task.task_id, **checked})
                docker.image = prepared[0][1]["image"]
                boot = NativeDriver(docker, docker.scratch / "boot", settings, "no-provider",
                    workspace_adapter=RepositoryWorkspace(prepared[0][1]["captured"]["base_files"], settings.max_patch_bytes))
                boot.invoke(prepared[0][1]["files"], "", boot_only=True)
                result["native_boot"] = "BOOTED"
                docker.image = base_image
                if arguments.command == "ab-preflight":
                    result["status"] = "READY_FOR_AB"
                else:
                    run_pairs(root, docker, prepared, settings, report, seed, arguments.allow_live_model, result)
        except KeyboardInterrupt:
            result["status"] = "CANCELLED"
        except (ValueError, OSError, RuntimeError) as error:
            result.update(status="AB_INCOMPLETE", reason=str(error)[:1500])
        finally:
            logs = {str(path.relative_to(docker.scratch)): path.read_text(encoding="utf-8", errors="replace")[-32768:]
                    for path in list(docker.scratch.rglob("process.log"))[:100]}
            build = docker.scratch / "image-build.log"
            if build.is_file():
                logs["image-build.log"] = build.read_text(encoding="utf-8", errors="replace")[-32768:]
            result["diagnostics_ref"] = report.cas.put_text(canonical_json(logs))
            docker.close()
    return result
