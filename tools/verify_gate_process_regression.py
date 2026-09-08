"""Exact old collection fails; new isolated phases pass on the same synthetic test layout."""
from pathlib import Path
import importlib.util
import json
import os
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'packages/benchmark_core')]
from tools.runtime_gate import run_phases
from tools.runtime_gate_worker import REGRESSION_SUITES
from tools.launcher_env import clean_environment

BASE = 'f41460baab73e8790cc1adc04aed45b49fedb291'


def main():
    spec = importlib.util.spec_from_file_location('gate_layout_fixture', ROOT / 'tests/coding/gate_layout_fixture.py')
    fixture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture)
    old_source = subprocess.run(['git', '-C', str(ROOT), 'show', BASE + ':tools/runtime_gate.py'],
                               check=True, capture_output=True).stdout
    # Exercise the old main verbatim; only distribution identity and final receipt
    # identity are replaced in this explicitly synthetic test harness.
    with tempfile.TemporaryDirectory(prefix='gate-import-regression-') as temporary:
        root, private, events = fixture.layout(Path(temporary), require_order=False)
        old_path = root / 'tools/old_runtime_gate.py'
        old_path.write_bytes(old_source)
        bootstrap = root / 'tools/run_old.py'
        bootstrap.write_text('import importlib.util, sys\nfrom pathlib import Path\n'
            + 'sys.path.insert(0, ' + repr(str(ROOT)) + ')\n'
            'from suites.coding import adcp_loading\n'
            'adcp_loading.verify_distribution = lambda path: None  # synthetic layout only\n'
            'spec = importlib.util.spec_from_file_location("old_gate", Path(__file__).with_name("old_runtime_gate.py"))\n'
            'module = importlib.util.module_from_spec(spec)\nspec.loader.exec_module(module)\n'
            'module.gate_identity = lambda *args: "synthetic-old"\n'
            + 'sys.argv = [__file__, ' + repr(str(private)) + ']\n'
            'raise SystemExit(module.main())\n', encoding='utf-8')
        old = subprocess.run([sys.executable, '-I', '-B', str(bootstrap)], cwd=private,
            env=clean_environment(ROOT), capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=90)
        expected = "No module named 'tests.architecture_governance'"
        if old.returncode == 0 or expected not in old.stdout + old.stderr:
            raise AssertionError('Exact previous gate did not reproduce the reported import error:\n' + old.stdout + old.stderr)
        if events.exists():
            raise AssertionError('The old collection error unexpectedly executed tests')
        result = run_phases(root, private, root / 'reports', 'synthetic-new', timeout=90)
        if result['counts'] != {'testcase': 65, 'failure': 0, 'error': 0, 'skipped': 0}:
            raise AssertionError('The new gate did not execute every layout probe')
        receipt = {'scope': 'SYNTHETIC_IMPORT_LAYOUT_NOT_PRIVATE_RUNTIME', 'platform': sys.platform,
            'baseline_commit': BASE, 'old_exit': old.returncode, 'old_error': expected,
            'new_counts': result['counts'], 'sequence': events.read_text().splitlines(),
            'private_runtime_executed': False, 'model_called': False}
        output = ROOT / 'artifacts/gate-process-regression.json'
        output.parent.mkdir(exist_ok=True)
        output.write_text(json.dumps(receipt, indent=2), encoding='utf-8')
        print(json.dumps(receipt, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
