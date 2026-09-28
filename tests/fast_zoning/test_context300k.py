from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from suites.auto_zoning.context300k import corpus, verify, count, _fit, ARMS, PILOT_SEEDS, CONFIRM_SEEDS
from suites.auto_zoning.context300k_workload import TASKS, configuration, sources
from suites.auto_zoning.context300k_evaluation import qualify_controls, score_decisions
from suites.auto_zoning.context300k_metrics import preflight, overlap, account_arm, compare

class CharacterTokenizer:
    # Deliberately synthetic reference tokenizer; never a provider-context claim.
    def encode(self,text,add_special_tokens=False):
        return SimpleNamespace(ids=[ord(c) for c in text],offsets=[(i,i+1) for i in range(len(text))])
    def decode(self,ids,skip_special_tokens=False):return ''.join(map(chr,ids))

@pytest.mark.parametrize('seed',(*PILOT_SEEDS,*CONFIRM_SEEDS))
def test_reference_and_each_component_negative_control(seed):
    report=qualify_controls(seed)
    assert report['reference_pass'],report['reference_failures']
    assert report['all_defects_detected']
    assert report['checks']>=130 and report['model_calls']==0
    assert {r['task_id'] for r in report['negative_controls']}=={t[0] for t in TASKS}


def test_exact_frozen_history_and_cross_context_facts():
    tokenizer=CharacterTokenizer()
    text,truth,meta=corpus(17011,tokenizer)
    assert count(tokenizer,text)==300000
    assert meta['origin']=='synthetic_T0_replay'
    assert meta['critical_source_messages']==2*len(configuration(17011))
    assert len(truth)==len(configuration(17011))
    assert all(len(row['sources'])==2 for row in truth.values())
    assert any(.4<loc['fraction']<.6 for row in truth.values() for loc in row['locations'])
    assert any(loc['fraction']>.9 for row in truth.values() for loc in row['locations'])
    assert all(mid in text for row in truth.values() for mid in row['sources'])
    other,other_truth,_=corpus(17011,tokenizer)
    assert other==text and truth==other_truth


def test_token_fitting_exact_not_bytes_divided_by_four():
    tokenizer=CharacterTokenizer()
    assert count(tokenizer,_fit(tokenizer,'already much longer text',9))==9
    assert count(tokenizer,_fit(tokenizer,'x',40))==40


def test_reference_is_not_identical_to_visible_start():
    c=configuration(43013)
    baseline,reference=sources(c,True),sources(c)
    assert baseline['parcelgrid/legacy_io.py']==reference['parcelgrid/legacy_io.py']
    assert all(baseline[f'parcelgrid/{module}.py']!=reference[f'parcelgrid/{module}.py'] for _,module,_,_ in TASKS)


def test_partial_or_stale_fact_lookup_not_full_recall():
    oracle=dict(facts={'ttl_ms':dict(value=120000,sources=['value','approval'],obsolete_sources=['draft'])})
    assert score_decisions(oracle,dict(choices=[dict(key='ttl_ms',value=120000,sources=['value'])]))['correct']==0
    assert score_decisions(oracle,dict(choices=[dict(key='ttl_ms',value=120000,sources=['value','approval','draft'])]))['correct']==0
    assert score_decisions(oracle,dict(choices=[dict(key='ttl_ms',value=120000,sources=['value','approval'])]))['correct']==1
    assert score_decisions(oracle,dict(choices=[]))['omitted']==1
    with pytest.raises(ValueError):score_decisions(oracle,dict(choices=[dict(key='x'),dict(key='x')]))


def test_unregistered_file_and_modified_oracle_fail_seal(tmp_path):
    from suites.auto_zoning.context300k import sha
    data=tmp_path/'public';data.mkdir();f=data/'history.txt';f.write_text('history')
    (tmp_path/'sealed-files.json').write_text(json.dumps({'public/history.txt':sha(f.read_bytes())}))
    assert verify(tmp_path)['model_execution_verified'] is False
    (data/'answers.json').write_text('{}')
    with pytest.raises(ValueError,match='Unexpected'):verify(tmp_path)
    (data/'answers.json').unlink();f.write_text('changed')
    with pytest.raises(ValueError,match='changed'):verify(tmp_path)


def profile():
    keys=['same_exact_model_revision','model_tokenizer_capacity_and_active_checkpoint_receipt',
       'native_context_import_no_silent_truncation','TaskOwner_admission_for_source_and_session_roles',
       'same_tools_and_model_budgets','private_evaluator_not_mounted','provider_usage_accounting',
       'fresh_arm_workspaces_profiles_databases','explicit_dispatch_authorization']
    result=dict.fromkeys(keys,True)
    result.update(model_id='fixture-model',model_revision='pinned',model_context_limit=400000,
                  model_tokenized_history_tokens=300000,output_and_tools_reserve_tokens=32768)
    for key in ['native_request_receipt_sha256','model_tokenizer_sha256','owner_admission_receipt_sha256','protected_evaluator_receipt_sha256']:
        result[key]='a'*64
    return result

@pytest.mark.parametrize('field,value',[
 ('model_context_limit',200000),('model_tokenized_history_tokens',299999),('model_revision',None),
 ('private_evaluator_not_mounted',False),('native_context_import_no_silent_truncation',False),
 ('TaskOwner_admission_for_source_and_session_roles',False),('explicit_dispatch_authorization',False),
 ('native_request_receipt_sha256',None),('output_and_tools_reserve_tokens',None)])
def test_launch_preflight_rejects_unverified_or_unfair_run(field,value):
    p=profile();p[field]=value
    assert not preflight({'primary_target':300000},p)['ready']
    assert preflight({'primary_target':300000},profile())['ready']


def native_trace(total=12345):
    usage=dict(input=12000,output=345,cacheRead=0,cacheWrite=0,reasoningTokens=0,totalTokens=total)
    events=[dict(type='message_end',message=dict(role='assistant',stopReason='stop',usage=usage)),dict(type='agent_end',isTerminal=True)]
    return '\n'.join(json.dumps(e) for e in events).encode()


def receipt():
    spans=[dict(task_id=task,session_id='one',start_ns=(i+1)*10**9,end_ns=(i+2)*10**9) for i,(task,_,_,_) in enumerate(TASKS)]
    return dict(history_sha256='h',oracle_sha256='o',production_path_verified=True,private_evaluator_visible=False,
      initial_model_context_tokens=300000,all_llm_work_included=True,model_id='fixture',model_revision='v1',
      model_tokenizer_verified=True,compaction_policy_equal=True,task_spans=spans,start_ns=0,accepted_end_ns=10*10**9,
      accepted_task_ids=[t[0] for t in TASKS],legacy_regression_pass=True,process_exit=0,model_request_spans=[],
      final_source_sha256='f'*64,origin='native_measured')


def test_wall_time_is_critical_path_not_sum():
    stats=overlap([dict(start_ns=0,end_ns=10),dict(start_ns=2,end_ns=6),dict(start_ns=6,end_ns=8)])
    assert stats==dict(peak_active=2,overlap_ns=6)
    assert overlap([dict(start_ns=0,end_ns=1),dict(start_ns=1,end_ns=2)])['peak_active']==1
    with pytest.raises(ValueError):overlap([dict(start_ns=2,end_ns=1)])


def test_speed_and_tokens_only_compared_at_equal_quality():
    plan=dict(arms=ARMS,primary_target=300000);variant=dict(history_sha256='h',oracle_sha256='o')
    a=account_arm(plan,variant,'A1',receipt(),native_trace())
    b=account_arm(plan,variant,'B4',receipt(),native_trace(10000))
    assert a['eligible'] and b['eligible']
    assert compare(a,b,variant)['token_saving_at_equal_quality']>0
    bad=receipt();bad['accepted_task_ids']=[]
    b=account_arm(plan,variant,'B4',bad,native_trace(500))
    assert compare(a,b,variant)['token_saving_at_equal_quality'] is None
    assert compare(a,b,variant)['speedup_at_equal_quality'] is None


def test_missing_usage_never_turned_into_zero():
    plan=dict(arms=ARMS,primary_target=300000);v=dict(history_sha256='h',oracle_sha256='o')
    a=account_arm(plan,v,'A1',receipt(),native_trace())
    b=account_arm(plan,v,'B4',receipt(),native_trace(None))
    assert b['provider_total_tokens'] is None
    assert compare(a,b,v)['token_saving_at_equal_quality'] is None

@pytest.mark.parametrize('change', ['seed','truncated','oracle','model','compaction','synthetic','missing_task','parallel_A','dependent_early'])
def test_invalid_measurement_cannot_support_win(change):
    r=receipt()
    if change=='seed':r['history_sha256']='other'
    elif change=='truncated':r['initial_model_context_tokens']=10000
    elif change=='oracle':r['private_evaluator_visible']=True
    elif change=='model':r['model_id']=None
    elif change=='compaction':r['compaction_policy_equal']=False
    elif change=='synthetic':r['origin']='unit_test'
    elif change=='missing_task':r['task_spans']=r['task_spans'][:-1]
    elif change=='parallel_A':r['task_spans'][1]['start_ns']=r['task_spans'][0]['start_ns']
    else:r['task_spans'][-1]['start_ns']=0
    arm=account_arm(dict(arms=ARMS,primary_target=300000),dict(history_sha256='h',oracle_sha256='o'),'A1',r,native_trace())
    assert not arm['eligible']


def test_native_abort_is_not_success_even_when_process_exit_zero():
    events=[dict(type='message_end',message=dict(role='assistant',stopReason='aborted')),dict(type='agent_end',isTerminal=True)]
    arm=account_arm(dict(arms=ARMS,primary_target=300000),dict(history_sha256='h',oracle_sha256='o'),'A1',receipt(),
                    '\n'.join(json.dumps(e) for e in events).encode())
    assert not arm['eligible'] and 'native_not_successfully_completed' in arm['errors']



def test_empty_campaign_never_claims_a_win():
    from suites.auto_zoning.context300k_metrics import campaign_report,dispatch_descriptors
    plan=dict(primary_target=300000,arms=ARMS,variants=[dict(variant='v',phase='CONFIRMATORY')])
    report=campaign_report(plan,[])
    assert report['automatic_architecture_winner'] is None
    assert report['quality_difference'] is None and report['missing']==['v']
    with pytest.raises(ValueError):dispatch_descriptors(plan,dict(variant='v',history_sha256='h'),'B4',{})
    descriptor=dispatch_descriptors(plan,dict(variant='v',history_sha256='h'),'B4',profile())
    assert len(descriptor['tasks'])==8
    assert all(t['owner_task_id'] is None for t in descriptor['tasks'])
