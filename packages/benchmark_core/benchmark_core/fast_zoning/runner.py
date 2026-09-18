"""Once-only paired execution with durable intent and independent evaluator copies."""
import json
from importlib.resources import files
import os
from pathlib import Path
import re
import subprocess
import time
from .manifest import InvalidManifest, PacketQualityPending, validate_manifest, digest_bytes, plan_digest
from .gitops import clone_snapshot, verify_source, capture_patch, apply_patch
from .storage import write_json, state, claim
from .evaluation import run_evaluators
from .events import parse_jsonl
from .results import qualify_arm, paired_summary
from .lab_backend import LabBackend, production_backend, run_arm, export_observability


def command(config, workspace, packet):
    return [config['omp_executable'], '--cwd', str(workspace), '--mode', 'json',
            '--no-session', '--model', config['model'], '--auto-approve', '--tools',
            config['tools'], '--max-time', config['max_time'], '@' + str(packet)]


def plan_campaign(manifest_path, campaign_dir, pair_run_id):
    campaign_dir = Path(campaign_dir).resolve()
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', pair_run_id):
        raise InvalidManifest('unsafe pair_run_id')
    try:
        manifest = validate_manifest(manifest_path)
    except InvalidManifest as exc:
        destination = campaign_dir / 'invalid' / pair_run_id
        destination.mkdir(parents=True, exist_ok=False)
        state(destination, 'PACKETS_IMPORTED' if isinstance(exc, PacketQualityPending) else 'INVALID_MANIFEST',
              error=str(exc), model_executed=False)
        raise
    pair_dir = campaign_dir / 'tasks' / manifest['task_id'] / pair_run_id
    pair_dir.mkdir(parents=True, exist_ok=False)
    state(pair_dir, 'PLANNED', campaign_id=campaign_dir.name, task_id=manifest['task_id'],
          pair_run_id=pair_run_id, model_executed=False)
    try:
        state(pair_dir, 'VALIDATED')
        write_json(pair_dir / 'task.json', manifest)
        write_json(campaign_dir / 'manifest.json', {'schema_version':1,'campaign_id':campaign_dir.name})
        arms = {}
        lab_route = manifest['execution']['route'] == 'LAB_HOST_ONLY'
        scaffold = files('benchmark_core.fast_zoning').joinpath('instructions.md').read_bytes()
        for arm in ('A','B'):
            arm_dir = pair_dir / arm
            arm_dir.mkdir()
            workspace = (Path(manifest['repo']) if lab_route else
                         clone_snapshot(manifest['repo'], arm_dir / 'workspace',
                                        manifest['buggy_head'], manifest['buggy_tree']))
            packet = Path(manifest['contexts'][arm]['packet_path']).read_bytes()
            (arm_dir / 'context.md').write_bytes(packet)
            # Both envelopes have identical scaffold/task; context is the sole variable.
            execution_packet = scaffold + b'\n# Task\n\n' + manifest['task_text'].encode() + b'\n\n# Context\n\n' + packet
            if lab_route:
                execution_packet = packet
            packet_path = arm_dir / 'packet.md'
            packet_path.write_bytes(execution_packet)
            arms[arm] = {'workspace':str(workspace), 'packet_path':str(packet_path),
                'packet_hash':digest_bytes(execution_packet), 'context_hash':digest_bytes(packet),
                'task_hash':manifest['task_hash'], 'evaluation_plan_digest':manifest['evaluation_plan_digest'],
                'argv':None if lab_route else command(manifest['execution'],workspace,packet_path)}
        plan = {'schema_version':1,'campaign_id':campaign_dir.name,'task_id':manifest['task_id'],
            'pair_run_id':pair_run_id,'pair_dir':str(pair_dir),'run_order':manifest['_run_order'],
            'run_order_seed':manifest['run_order_seed'],'evaluation_plan_digest':manifest['evaluation_plan_digest'],
            'evaluation_plan':manifest['evaluation_plan'],'phase':'PREDECLARED','arms':arms,
            'manifest_hash':manifest['_manifest_hash']}
        write_json(pair_dir / 'plan.json',plan)
        write_json(pair_dir / 'seal.json',{'plan_hash':plan_digest(plan),
            'task_hash':digest_bytes((pair_dir / 'task.json').read_bytes())})
        state(pair_dir,'READY')
        return plan
    except Exception as exc:
        state(pair_dir,'INFRA_FAILURE',error=str(exc))
        raise


def _execute(argv, cwd, stdout_path, stderr_path, env):
    start = time.perf_counter()
    with Path(stdout_path).open('wb') as stdout, Path(stderr_path).open('wb') as stderr:
        try:
            process = subprocess.run(argv,cwd=cwd,stdout=stdout,stderr=stderr,env=env,timeout=660)
            code = process.returncode
        except subprocess.TimeoutExpired:
            code = None
    return {'exit_code':code,'model_wall_time':time.perf_counter()-start}


def _guard(pair_dir, plan, seal, manifest, arm=None):
    if plan_digest(json.loads((pair_dir/'plan.json').read_text())) != seal['plan_hash']:
        raise InvalidManifest('frozen plan changed')
    if digest_bytes((pair_dir/'task.json').read_bytes()) != seal['task_hash']:
        raise InvalidManifest('frozen task changed')
    checked = validate_manifest(manifest['_manifest_path'])
    if checked['_manifest_hash'] != plan['manifest_hash']:
        raise InvalidManifest('source manifest changed')
    for name,item in plan['arms'].items():
        if digest_bytes(Path(item['packet_path']).read_bytes()) != item['packet_hash']:
            raise InvalidManifest('frozen execution packet changed')
        if digest_bytes((pair_dir/name/'context.md').read_bytes()) != item['context_hash']:
            raise InvalidManifest('frozen context changed')
    if arm is not None:
        verify_source(plan['arms'][arm]['workspace'],manifest['buggy_head'],manifest['buggy_tree'])


def execute_pair(pair_dir, authorized=False, executor=None, *, lab_backend: LabBackend | None = None):
    if not authorized:
        raise PermissionError('real execution requires explicit authorization')
    pair_dir = Path(pair_dir).resolve()
    if (pair_dir/'execution.claim').exists():
        raise FileExistsError('pair execution already claimed; create a new pair run ID')
    plan = json.loads((pair_dir / 'plan.json').read_text())
    seal = json.loads((pair_dir / 'seal.json').read_text())
    try:
        if plan_digest(plan) != seal['plan_hash'] or digest_bytes((pair_dir/'task.json').read_bytes()) != seal['task_hash']:
            raise InvalidManifest('frozen plan/task changed')
        manifest = json.loads((pair_dir / 'task.json').read_text())
        lab_route = manifest['execution']['route'] == 'LAB_HOST_ONLY'
        if lab_route and executor is not None:
            raise InvalidManifest('executor hook is prohibited for LAB_HOST_ONLY')
        if not lab_route and lab_backend is not None:
            raise InvalidManifest('lab_backend requires LAB_HOST_ONLY')
        checked = validate_manifest(manifest['_manifest_path'])
        if checked['_manifest_hash'] != plan['manifest_hash']:
            raise InvalidManifest('source manifest changed')
        for arm in ('A','B'):
            item = plan['arms'][arm]
            verify_source(item['workspace'],manifest['buggy_head'],manifest['buggy_tree'])
            if digest_bytes(Path(item['packet_path']).read_bytes()) != item['packet_hash']:
                raise InvalidManifest('frozen execution packet changed')
        claim(pair_dir/'execution.claim')
    except (InvalidManifest,ValueError,OSError) as exc:
        state(pair_dir,'INVALID_MANIFEST',error=str(exc))
        raise InvalidManifest(str(exc)) from exc
    environment = dict(os.environ)
    environment_digest = plan_digest(environment)
    executable_hash = None
    # Version verification belongs only to authorized real execution, never dry-run.
    if executor is None and not lab_route:
        try:
            executable_hash = digest_bytes(Path(manifest['execution']['omp_executable']).read_bytes())
            version = subprocess.run([manifest['execution']['omp_executable'],'--version'],
                                      capture_output=True,text=True,timeout=30,env=environment)
            reported_versions = re.findall(r'(?<![\d.])\d+\.\d+\.\d+(?![\d.])',version.stdout)
            if version.returncode or reported_versions != [manifest['execution']['omp_version']]:
                raise RuntimeError('OMP version mismatch')
        except Exception as exc:
            state(pair_dir,'INFRA_FAILURE',error=str(exc))
            raise
    write_json(pair_dir/'execution-environment.json',{'environment_digest':environment_digest,
               'executable_sha256':executable_hash,'execution':manifest['execution']})
    execution = executor or _execute
    metrics = {}
    infra = False
    for arm in plan['run_order']:
        arm_dir = pair_dir / arm
        item = plan['arms'][arm]
        start = time.perf_counter()
        try:
            _guard(pair_dir,plan,seal,manifest,arm)
            if executable_hash is not None and digest_bytes(Path(manifest['execution']['omp_executable']).read_bytes()) != executable_hash:
                raise InvalidManifest('OMP executable changed during pair')
        except Exception as exc:
            state(pair_dir,'INVALID_MANIFEST',error=str(exc),pair_invalidated=True)
            raise InvalidManifest(str(exc)) from exc
        state(pair_dir,'RUNNING_'+arm,arm=arm)
        claim(arm_dir/'invocation.claim')
        if lab_route:
            state(pair_dir, 'EVALUATING', arm=arm)
            parsed, evaluation, patch_valid = run_arm(lab_backend or production_backend,
                manifest=manifest, plan=plan, arm=arm, arm_dir=arm_dir)
            write_json(arm_dir/'lab-evidence.json', parsed.get('lab_evidence', {'error': parsed.get('error')}))
        else:
            (arm_dir/'raw.jsonl').touch()
            (arm_dir/'stderr.log').touch()
            try:
                process = execution(item['argv'],item['workspace'],arm_dir/'raw.jsonl',arm_dir/'stderr.log',dict(environment))
            except Exception as exc:
                process = {'exit_code':None,'model_wall_time':time.perf_counter()-start,'error':str(exc)}
            parsed = parse_jsonl((arm_dir/'raw.jsonl').read_bytes(),process.get('exit_code'),Path(item['workspace']))
            parsed.update(process)
            patch_valid = None
            evaluation = {'evaluation_plan_digest':manifest['evaluation_plan_digest'],'results':{}}
            state(pair_dir,'EVALUATING',arm=arm)
            try:
                patch = capture_patch(item['workspace'],manifest['buggy_head'],arm_dir)
                parsed.update(patch)
                evaluation_workspace = clone_snapshot(manifest['repo'],arm_dir/'evaluation-workspace',
                    manifest['buggy_head'],manifest['buggy_tree'])
                try:
                    apply_patch(evaluation_workspace,arm_dir/'patch.diff')
                    patch_valid = True
                except subprocess.CalledProcessError:
                    patch_valid = False
                    raise
                evaluation = run_evaluators(manifest,evaluation_workspace,arm_dir/'evaluators')
            except Exception as exc:
                evaluation = {'evaluation_plan_digest':manifest['evaluation_plan_digest'],
                    'results':{row['id']:{'status':'ERROR','error':str(exc)} for row in manifest['_evaluators']},
                    'error':str(exc)}
        context = manifest['contexts'][arm]
        parsed.update(invocation_attempted=True, retries=0)
        if lab_route:
            parsed['policy_packet_bytes'] = context['packet_bytes']
            for field in ('packet_bytes', 'source_bytes', 'source_item_count', 'total_wall_time'):
                parsed.setdefault(field, None)
        else:
            parsed.update(model_executed=parsed['model_turns'] > 0, packet_bytes=context['packet_bytes'],
                source_bytes=context['source_bytes'],source_item_count=context['source_item_count'],
                zoning_time=context.get('zoning_time'),planning_time=context.get('planning_time'),
                preprocessing_time=context.get('preprocessing_time'),total_cost=None,quota_usage=None)
        write_json(arm_dir/'evaluation.json',evaluation)
        parsed['execution_and_evaluation_wall_time'] = time.perf_counter()-start
        if not lab_route:
            parsed['total_wall_time'] = (parsed['execution_and_evaluation_wall_time'] + context['preprocessing_time']
                                        if context.get('preprocessing_time') is not None else None)
        qualified = qualify_arm({**manifest['evaluation_plan'],'evaluation_plan_digest':manifest['evaluation_plan_digest']},
                                evaluation,parsed,patch_valid=patch_valid)
        metrics[arm] = qualified
        write_json(arm_dir/'metrics.json',qualified)
        if lab_route:
            export_observability(manifest=manifest, directory=arm_dir)
        # The selected backend must explicitly prove execution success.
        process_ok = parsed.get('execution_success') is True
        infra = infra or not process_ok or patch_valid is not True or any(row['status']=='ERROR' for row in evaluation['results'].values())
    summary = paired_summary({**manifest['evaluation_plan'],'evaluation_plan_digest':manifest['evaluation_plan_digest']},metrics['A'],metrics['B'])
    summary.update(pair_run_id=plan['pair_run_id'],task_id=plan['task_id'],campaign_id=plan['campaign_id'],
                   status='INFRA_FAILURE' if infra else 'COMPLETED')
    write_json(pair_dir/'paired-summary.json',summary)
    model_executed = (True if any(row['model_executed'] is True for row in metrics.values()) else
                      None if any(row['model_executed'] is None for row in metrics.values()) else False)
    state(pair_dir,summary['status'],arm=None,model_executed=model_executed)
    if lab_route:
        export_observability(manifest=manifest, directory=pair_dir, paired=True)
    return summary
