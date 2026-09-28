# Evidence-bound offline accounting; no inferred usage, artificial sleeps or winner labels.
from __future__ import annotations
import math
from benchmark_core.fast_zoning.events import parse_jsonl
from benchmark_core.fast_zoning.results import paired_summary
from .context300k_workload import TASKS


def overlap(spans):
    points=[]
    for row in spans:
        a,b=row['start_ns'],row['end_ns']
        if type(a) is not int or type(b) is not int or a<0 or b<a:raise ValueError('Invalid monotonic interval')
        points.extend([(a,1),(b,-1)] if b>a else [])
    active=peak=parallel_ns=0;previous=None
    for at,delta in sorted(points):
        if previous is not None and active>=2:parallel_ns+=at-previous
        active+=delta;peak=max(peak,active);previous=at
    return dict(peak_active=peak,overlap_ns=parallel_ns)


def preflight(plan, profile):
    errors=[]
    needed=['same_exact_model_revision','model_tokenizer_capacity_and_active_checkpoint_receipt',
            'native_context_import_no_silent_truncation','TaskOwner_admission_for_source_and_session_roles',
            'same_tools_and_model_budgets','private_evaluator_not_mounted','provider_usage_accounting',
            'fresh_arm_workspaces_profiles_databases','explicit_dispatch_authorization']
    for name in needed:
        if profile.get(name) is not True:errors.append(name)
    target=plan['primary_target']
    if not profile.get('model_id') or not profile.get('model_revision'):errors.append('unpinned_model')
    capacity=profile.get('model_context_limit');body=profile.get('model_tokenized_history_tokens');reserve=profile.get('output_and_tools_reserve_tokens')
    if not all(type(v) is int and v>=0 for v in [capacity,body,reserve]) or body<target or capacity<body+reserve:
        errors.append('300k_active_model_window_not_proven')
    for name in ['native_request_receipt_sha256','model_tokenizer_sha256','owner_admission_receipt_sha256','protected_evaluator_receipt_sha256']:
        if not isinstance(profile.get(name),str) or len(profile[name])!=64:errors.append(name)
    return dict(ready=not errors,errors=errors,model_calls=0,
                note='Presented host receipts must be authenticated by the existing owner before dispatch')


def account_arm(plan,variant,arm,receipt,trace_bytes):
    errors=[]
    if arm not in plan['arms']:raise ValueError('Unknown arm')
    if receipt.get('history_sha256')!=variant['history_sha256']:errors.append('unequal_history')
    if receipt.get('oracle_sha256')!=variant['oracle_sha256']:errors.append('changed_hidden_oracle')
    if receipt.get('production_path_verified') is not True:errors.append('unverified_runtime_path')
    if receipt.get('private_evaluator_visible') is not False:errors.append('oracle_isolation_unproven')
    size=receipt.get('initial_model_context_tokens')
    if type(size) is not int or size<plan['primary_target']:errors.append('initial_context_below_300k')
    if not receipt.get('model_id') or not receipt.get('model_revision'):errors.append('unpinned_model')
    if receipt.get('model_tokenizer_verified') is not True:errors.append('reference_count_not_active_window')
    if receipt.get('compaction_policy_equal') is not True:errors.append('unfair_baseline_compaction')
    if receipt.get('all_llm_work_included') is not True:errors.append('missing_setup_routing_retry_usage')
    tasks=receipt.get('task_spans',[]);ids=[t['task_id'] for t in tasks]
    if len(ids)!=len(set(ids)) or set(ids)!={t[0] for t in TASKS}:errors.append('incomplete_task_inventory')
    by_id={t['task_id']:t for t in tasks}
    for task,_,deps,_ in TASKS:
        if task not in by_id:continue
        for dep in deps:
            if dep not in by_id or by_id[task]['start_ns']<by_id[dep]['end_ns']:errors.append('prerequisite_overlap')
    concurrency=overlap(tasks)
    if concurrency['peak_active']>plan['arms'][arm]['max_active_tasks']:errors.append('concurrency_limit')
    if arm=='A1' and len({t['session_id'] for t in tasks})!=1:errors.append('A1_not_single_session')
    start,end=receipt.get('start_ns'),receipt.get('accepted_end_ns')
    if type(start) is not int or type(end) is not int or end<=start:errors.append('wall_time_unknown');wall=None
    else:
        wall=(end-start)/1e9
        if any(t['start_ns']<start or t['end_ns']>end for t in tasks):errors.append('uncharged_phase')
    usage=parse_jsonl(trace_bytes,receipt.get('process_exit'))
    # Existing classifier treats timeout/error exit zero as failure, not completion.
    if not usage['execution_success'] or not usage['model_turns']:errors.append('native_not_successfully_completed')
    passed=receipt.get('accepted_task_ids',[])
    if len(set(passed))!=len(passed) or not set(passed)<={t[0] for t in TASKS}:errors.append('invalid_quality_inventory')
    result=dict(usage,arm=arm,errors=sorted(set(errors)),eligible=not errors,
      quality_tasks=len(passed),semantic_success='YES' if len(passed)==len(TASKS) and receipt.get('legacy_regression_pass') is True else 'NO',
      total_wall_time=wall,task_concurrency=concurrency,model_concurrency=overlap(receipt.get('model_request_spans',[])),
      model_id=receipt.get('model_id'),model_revision=receipt.get('model_revision'),
      final_source_sha256=receipt.get('final_source_sha256'),evaluation_plan_digest=variant['oracle_sha256'],evaluation_phase='PREDECLARED',
      origin=receipt.get('origin'))
    if result['origin']!='native_measured':result['eligible']=False;result['errors'].append('synthetic_or_unproven_execution')
    return result


def compare(a,b,variant):
    ready=(a.get('eligible') and b.get('eligible') and a.get('model_id')==b.get('model_id')
           and a.get('model_revision')==b.get('model_revision'))
    if not ready:return dict(status='INCONCLUSIVE',reason='unmatched_or_unverified_execution',speedup=None,token_saving=None)
    result=paired_summary(dict(phase='PREDECLARED',evaluation_plan_digest=variant['oracle_sha256']),a,b)
    equal=result['quality_comparison']=='EQUIVALENT_ON_PREDECLARED_EVALUATION'
    result['speedup_at_equal_quality']=a['total_wall_time']/b['total_wall_time'] if equal and b['total_wall_time'] else None
    result['token_saving_at_equal_quality']=result['resource_comparison']['equal_quality_token_saving']
    result['quality_task_difference']=b['quality_tasks']-a['quality_tasks']
    result['observed_model_parallelism']=b['model_concurrency']
    return result



def campaign_report(plan,pairs,*,resamples=5000):
    # One seed/task batch is one paired unit; individual asserts are not replicates.
    import random
    from statistics import mean
    expected={v['variant'] for v in plan['variants'] if v['phase']=='CONFIRMATORY'}
    identities=[p['variant'] for p in pairs]
    if len(identities)!=len(set(identities)) or not set(identities)<=expected:
        raise ValueError('Duplicate, pilot or unknown paired unit')
    lookup={v['variant']:v for v in plan['variants']}
    analyzed=[dict(variant=p['variant'],result=compare(p['A1'],p['B4'],lookup[p['variant']])) for p in pairs]
    valid=[p for p in pairs if compare(p['A1'],p['B4'],lookup[p['variant']]).get('status')=='COMPLETED']
    def interval(values):
        if not values:return None
        rng=random.Random(884731)
        samples=sorted(mean(rng.choices(values,k=len(values))) for _ in range(resamples))
        return dict(n=len(values),mean=mean(values),low=samples[int(.025*(resamples-1))],high=samples[int(.975*(resamples-1))])
    quality=[(p['B4']['quality_tasks']-p['A1']['quality_tasks'])/len(TASKS) for p in valid]
    equal=[p for p in valid if p['A1']['semantic_success']==p['B4']['semantic_success']=='YES']
    speed=[p['A1']['total_wall_time']/p['B4']['total_wall_time'] for p in equal if p['B4']['total_wall_time']]
    saving=[1-p['B4']['provider_total_tokens']/p['A1']['provider_total_tokens'] for p in equal
            if p['A1'].get('provider_total_tokens') and p['B4'].get('provider_total_tokens') is not None]
    return dict(status='COMPLETE_PAIRED_MEASUREMENTS' if set(identities)==expected and len(valid)==len(expected) and expected else 'INCOMPLETE_OR_DESCRIPTIVE_ONLY',
      expected_pairs=len(expected),received_pairs=len(pairs),eligible_pairs=len(valid),missing=sorted(expected-set(identities)),
      quality_difference=interval(quality),speedup_equal_quality=interval(speed),token_saving_equal_quality=interval(saving),
      all_pairs=analyzed,selection_warning='Resource ratios condition on equal final quality; also report all failed-run resource totals.',
      automatic_architecture_winner=None)


def dispatch_descriptors(plan,variant,arm,profile):
    # Pure finite descriptions for existing native adapters; no execution or scheduling.
    admission=preflight(plan,profile)
    if not admission['ready']:raise ValueError('Dispatch blocked: '+', '.join(admission['errors']))
    if arm not in plan['arms']:raise ValueError('Unknown arm')
    return dict(schema='benchmark.zone-context-work/1',arm=arm,variant=variant['variant'],
      history_sha256=variant['history_sha256'],role='CODER',runtime=plan['arms'][arm]['session_policy'],
      max_active_tasks=plan['arms'][arm]['max_active_tasks'],
      checkpoint='full history before any scored task; B builds its own routing',
      tasks=[dict(benchmark_task_id=task,owner_task_id=None,prerequisites=list(deps),
       source_paths=['parcelgrid/'+module+'.py'],instruction=description) for task,module,deps,description in TASKS],
      authority='TaskOwner assigns authoritative identities/permits, dispatch and completion; this descriptor cannot.',
      evaluator='existing protected test provider; private source/oracle files not mounted in model workspace')
