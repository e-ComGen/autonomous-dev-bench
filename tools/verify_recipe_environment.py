"""Build and execute real async/GitPython/plugin checks in fresh native environments; no models."""
from pathlib import Path
from dataclasses import replace
import importlib.util
import json
import os
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'packages/benchmark_core')]
from benchmark_core.identity import Sha256Digest
from corpus.qualification.files import capture_files, code_view
from corpus.qualification.policy import IssuePolicy
from corpus.qualification.evaluator import PytestEvaluator
from suites.coding.backends.native import NativeRuntime
from suites.coding.settings import Settings


def main():
    for name in ('GITHUB_TOKEN', 'GH_TOKEN', 'DEEPSEEK_API_KEY', 'OPENAI_API_KEY'):
        os.environ.pop(name, None)
    spec = importlib.util.spec_from_file_location('recipe_build_fixture', ROOT / 'tests/native/recipe_project_fixture.py')
    fixture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture)
    report = {'scope': 'REAL_NATIVE_TEST_ENVIRONMENT_FIXTURE_NOT_PAID_AB', 'model_called': False,
              'platform': sys.platform, 'status': 'FAILED'}
    artifacts = ROOT / 'artifacts'
    artifacts.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='recipe qualification ') as temporary:
        scratch = Path(temporary)
        fixture.write_project(scratch / 'source')
        runtime = NativeRuntime(ROOT, scratch / 'runs', Settings())
        runtime.scratch.mkdir()
        try:
            sdk = runtime.prepare_image()
            policy = replace(IssuePolicy(), build_seconds=300)
            files = capture_files(scratch / 'source', policy)
            task = {'base_files': files, 'projection': code_view(files, policy.max_code_bytes),
                    'test_overlay': {}, 'base_source_digest': str(Sha256Digest.of(files))}
            image, recipe = runtime.build_project_environment(task, policy, time.monotonic() + 600)
            assert recipe['dependency_group'] == 'dev'
            assert recipe['install'] == '.[testing]'
            assert recipe['local_projects'] == ['plugins/example']
            assert recipe['public_candidates'] == ['tests/test_recipe.py']
            evaluator = PytestEvaluator(runtime, ROOT, runtime.scratch / 'checks', task, image, 120)
            check = {'kind': 'public', 'paths': recipe['public_candidates']}
            baseline = task['projection']
            first = evaluator.observe(baseline, check)
            assert len(first) == 5 and set(first.values()) == {'PASS'}, first
            second = evaluator.observe(baseline, check)
            assert second == first
            changed = {**baseline, 'plugins/example/src/recipe_plugin.py': 'def answer():\n    return 8\n'}
            rejected = evaluator.score(changed, check, first)
            assert rejected['status'] == 'FAIL', rejected
            assert runtime.relay is None
            directory, manifest = runtime.environments.load(image)
            report.update(status='PASS', sdk=sdk, recipe=recipe, baseline=first, repeated_baseline=second,
                          edited_plugin_verdict=rejected['status'], frozen_wheels=manifest['wheels'],
                          fresh_environments=3, declared_dependencies=True, discarded_test_assets=False)
        except Exception as error:
            report['reason'] = str(error)[:2000]
            raise
        finally:
            runtime.close()
            (artifacts / 'recipe-environment.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
            logs = {str(path.relative_to(scratch)): path.read_text(encoding='utf-8', errors='replace')[-20000:]
                    for path in scratch.rglob('process.log')}
            (artifacts / 'recipe-environment-logs.json').write_text(json.dumps(logs, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
