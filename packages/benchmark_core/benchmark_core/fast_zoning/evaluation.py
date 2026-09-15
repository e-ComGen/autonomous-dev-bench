"""Only frozen evaluator commands run; structured status prevents exit-code guessing."""
import json
from pathlib import Path
import subprocess
from .manifest import digest_bytes
from .storage import write_json


def run_evaluators(manifest, workspace, output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    result = {'evaluation_plan_digest':manifest['evaluation_plan_digest'], 'results':{}}
    for index, evaluator in enumerate(manifest['_evaluators']):
        destination = output / str(index)
        destination.mkdir()
        try:
            replacements = {'workspace':str(Path(workspace).resolve())}
            for n, artifact in enumerate(evaluator['artifacts']):
                if digest_bytes(Path(artifact['path']).read_bytes()) != artifact['sha256']:
                    raise ValueError('frozen evaluator changed')
                replacements[f'artifact{n}'] = artifact['path']
            argv = [part.format_map(replacements) for part in evaluator['command']]
            process = subprocess.run(argv, cwd=workspace, capture_output=True,
                                     timeout=evaluator['timeout_seconds'])
            (destination / 'stdout.log').write_bytes(process.stdout)
            (destination / 'stderr.log').write_bytes(process.stderr)
            record = json.loads(process.stdout)
            if not isinstance(record,dict) or record.get('status') not in ('PASS','FAIL','ERROR'):
                raise ValueError('invalid evaluator result JSON')
            # FAIL requires explicit semantic evidence; process failure is never a PASS.
            if process.returncode and record['status'] != 'FAIL':
                record = {'status':'ERROR','error':'nonzero evaluator exit','exit_code':process.returncode}
            record['exit_code'] = process.returncode
        except (OSError, ValueError, KeyError, subprocess.TimeoutExpired) as exc:
            record = {'status':'ERROR','error':str(exc)}
        result['results'][evaluator['id']] = record
    write_json(output / 'evaluation.json', result)
    return result
