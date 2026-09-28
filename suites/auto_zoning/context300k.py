# Frozen long-context A/B preparation; no scheduler, model calls or acceptance authority.
from __future__ import annotations
import argparse
from bisect import bisect_left
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import random
import re
import subprocess
import sys
from benchmark_core.fast_zoning.storage import write_json
from .context300k_workload import TASKS, FACT_GROUPS, configuration, sources, cases

SCHEMA='benchmark.zone-context-ab/1'
TARGET=300000
PILOT_SEEDS=(17011,43013,91019)
CONFIRM_SEEDS=tuple(200003+7919*i for i in range(20))
ARMS={
 'A1':dict(session_policy='one_native_omp_session',max_active_tasks=1,context_policy='full_shared_checkpoint_then_native_compaction'),
 'B1':dict(session_policy='existing_taskowner_zone_sessions',max_active_tasks=1,context_policy='self_built_zones_from_same_shared_checkpoint'),
 'B4':dict(session_policy='existing_taskowner_zone_sessions',max_active_tasks=4,context_policy='self_built_zones_from_same_shared_checkpoint'),
 'A4':dict(session_policy='ordinary_omp_sessions_per_task',max_active_tasks=4,context_policy='same_history_access_no_handpicked_facts'),
}


def sha(data):
 return hashlib.sha256(data).hexdigest()


def canonical(value):
 return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)


def count(tokenizer,text):
 return len(tokenizer.encode(text,add_special_tokens=False).ids)


def _fit(tokenizer,text,n):
 # Only distractor tail may be cropped. Critical records are placed before it.
 ids=tokenizer.encode(text,add_special_tokens=False).ids
 while len(ids)<n:
  text+='\nArchived importer diagnostic row: '+('audit '*(n-len(ids)+32))
  ids=tokenizer.encode(text,add_special_tokens=False).ids
 fitted=tokenizer.decode(ids[:n],skip_special_tokens=False)
 for _ in range(16):
  actual=count(tokenizer,fitted)
  if actual==n:return fitted
  if actual<n:fitted+=' audit'*(n-actual)
  else:fitted=tokenizer.decode(tokenizer.encode(fitted,add_special_tokens=False).ids[:n],skip_special_tokens=False)
 raise ValueError('Tokenizer could not produce an exact round-trippable token count')


def _detail(key,value):
 details={
 'discount_bps':'Basis points, not percent. Apply only to the named cohort. Discount is rounded before cap; tax is calculated after discount.',
 'discount_cap':'Upper bound of the already rounded discount in integer cents, per whole order, not per item.',
 'tax_bps':'Tax is calculated on discounted net; round integer cents half up. Never calculate tax on the undiscounted subtotal.',
 'cohort':'Only this exact case-sensitive customer cohort receives the discount; all others receive zero discount.',
 'rounding':'For nonnegative amounts, round each stage to nearest cent with exact halves upward; do not use binary floats or bankers rounding.',
 'ttl_ms':'Reservation deadline equals at_ms plus this TTL; a release removes the named tenant-local hold. No change to physical stock.',
 'expiry_inclusive':'A hold is inactive when now_ms is exactly the deadline. Replay first, then subtract only remaining active holds. Overselling raises ValueError.',
 'dedupe_scope':'Duplicate identity consists of BOTH fields, not event_id alone. Replaying an identical event is a no-op.',
 'quantity_type':'Booleans, fractional, zero and negative quantities are invalid. Initial quantities and money are integer values.',
 'duplicate_conflict':'The same identity with different content is an error, never silently accepted. A reservation identity cannot be assigned again until released, even if a later query observes that the first hold expired.',
 'default_tenant':'Used only when tenant is absent. Empty supplied identities are invalid; do not normalize case or trim identity strings.',
 'order_field':'This field takes priority over order_id if present. Preserve other incoming fields; use order_id only as fallback.',
 'timestamp_unit':'at_ms must remain an integer in this unit, without multiplying or dividing by 1000. sequence is a nonnegative non-boolean integer.',
 'cancellation_alias':'This exact legacy value maps to release. Other accepted event kinds are reserve, release and delivery_failed.',
 'utc_offset':'Fixed UTC offset in hours, not a daylight-saving timezone. Convert an aware input instant into this local time.',
 'cutoff_hour':'At or after this local hour, move the dispatch anchor to the following date. Then roll the anchor forward to a business day.',
 'standard_days':'Add this many business days AFTER the dispatch anchor; the anchor itself is not counted.',
 'express_days':'Add this many business days AFTER the dispatch anchor. Unknown services or naive timestamps raise ValueError.',
 'weekend':'Python weekday indices. These days cannot count as dispatch anchors or delivery days.',
 'secret_fields':'Case-insensitive EXACT dictionary key matches at every depth, including dictionaries inside lists. token_count and order_id are not secret.',
 'mask':'Replacement string for sensitive values. Do not change keys, unrelated values, lists, input objects or identity fields.',
 'retry_statuses':'Only these response codes may retry. Normal 4xx, 500 and successes must not retry.',
 'retry_base_ms':'Exponential delay at retry_index zero; multiply by 2**retry_index then cap. No random jitter in this protocol.',
 'retry_cap_ms':'Cap all retry delays including Retry-After. Retry-After is a lower bound before applying this cap, in milliseconds.',
 'retry_limit':'Zero-based retry_index at or above this number stops retries. Negative, boolean or noninteger indexes and invalid Retry-After raise ValueError.',
 'checkout_stock_key':'Use this namespaced key. Multiply unit_cents by positive integer qty once, quote once, redact metadata and preserve all inputs.',
 'event_order':'Normalize first, sort by these two fields; event timestamp is not causal order. Replay stock and emit tenant/order_id/delay_ms retry summaries.',
 }
 return f'{key} = {canonical(value)}. '+details[key]


def _distractor(r,index):
 component=r.choice(['csv_header','archive_footer','empty_line','encoding_probe','batch_cursor','audit_counter','checksum','compression','resume_marker','delimiter'])
 mid='m-'+sha(f'distractor:{r.getrandbits(96)}'.encode())[:16]
 role=r.choice(['user','assistant','tool'])
 lead=r.choice([
  'T0 importer investigation: reproduce the boundary before changing the parser. This note does not amend downstream business policy.',
  'T0 retained tool output from the archive compatibility pass. The fixture IDs below belong to old migration samples.',
  'T0 review: keep the blank-line behavior and JSON object order intact; compare the recorded payload with the prior batch.',
  'T0 earlier hypothesis was rejected after checking the parser path. The current patch concerns archive ingestion only.',
  'T0 test log for a generated migration segment; source and sample IDs are independent of consumer configuration.',
 ])
 rows=[]
 for j in range(r.randint(9,20)):
  tag=r.choice(['observed','expected','sample','replayed','skipped_blank','roundtrip','decoded','checkpoint'])
  rows.append(f'{component}/{index:05}/{j:02}: {tag}; row={r.randrange(1000000)}; bytes={r.randrange(32,65536)}; batch={r.randrange(10000)}; source={r.getrandbits(64):016x}; retained=true.')
 if index%4==0:
  rows.extend(['def archive_probe(lines):','    objects = [decode_json(line) for line in lines if line.strip()]','    return objects  # T0: preserve ordering; downstream rules are separately approved.'])
 return f'\n[message {mid} role={role}]\n{lead}\n'+'\n'.join(rows)+'\n'


def corpus(seed,tokenizer,target=TARGET):
 if target<10000:raise ValueError('Preparation target must fit all independent source facts')
 r=random.Random(seed);c=configuration(seed);keys=sorted(c);r.shuffle(keys)
 sections=[[] for _ in range(20)];truth={};metadata=[]
 # Data values and independently approved references are separate facts.
 # Each bucket gets important records; late drafts are NOT newer authority.
 for i,key in enumerate(keys):
  bucket=[0,4,9,14,18][i%5]
  revision='contract-'+sha(f'{seed}:{key}:approved'.encode())[:12]
  value_id='m-'+sha((revision+':value').encode())[:16]
  approval_id='m-'+sha((revision+':approval').encode())[:16]
  stale_id='m-'+sha((revision+':stale').encode())[:16]
  value=f'\n[message {value_id} role=user]\nArchived contract excerpt {revision}, component review. {_detail(key,c[key])} This excerpt is effective only with its recorded approval.\n'
  approval=f'\n[message {approval_id} role=user]\nDecision ledger: {revision} is APPROVED for ParcelGrid production after T0. Earlier alternatives for {key} are superseded. A later unapproved draft must not change this contract.\n'
  wrong=(c[key]+111 if type(c[key]) is int else False if type(c[key]) is bool else ['archived-only'] if isinstance(c[key],list) else 'legacy-unapproved')
  stale=f'\n[message {stale_id} role=assistant]\nUNAPPROVED proposal for an unrelated migration branch: {key} = {canonical(wrong)}. No production approval, do not treat this draft as a replacement for the decision ledger.\n'
  sections[bucket].append(value);sections[min(19,bucket+1)].append(approval)
  sections[min(19,bucket+1)].append(stale)
  truth[key]=dict(value=c[key],sources=[value_id,approval_id],obsolete_sources=[stale_id],revision=revision)
 intro=('Frozen checkpoint of ONE completed task T0: migrate the legacy JSON-lines archive importer.\n'
        'This is a synthetic replay fixture, not a claimed prior model run. T0 is complete; legacy_io must remain correct.\n'
        'The transcript includes source excerpts, decisions, rejected proposals, tool outputs and tests.\n'
        'Approval, not the last textual mention, determines which downstream contract is effective.\n')
 result=[];index=0
 for bucket in range(20):
  base=(intro if bucket==0 else '')+f'\n=== T0 archive investigation segment {bucket+1:02} ===\n'
  r.shuffle(sections[bucket]);base+=''.join(sections[bucket])
  budget=target//20
  if count(tokenizer,base)>budget//2:raise ValueError('Fact density too high for requested corpus')
  buffer=[base];size=count(tokenizer,base)
  while size<budget+100:
   chunk=_distractor(r,index);index+=1;buffer.append(chunk);size+=count(tokenizer,chunk)
  result.append(_fit(tokenizer,''.join(buffer),budget))
 text=_fit(tokenizer,'\n'.join(result),target)
 encoded=tokenizer.encode(text,add_special_tokens=False)
 starts=[a for a,b in encoded.offsets]
 for key,entry in truth.items():
  positions=[]
  for mid in entry['sources']:
   needle=f'[message {mid} '
   if text.count(needle)!=1:raise ValueError('Missing or duplicate critical fact after token fitting')
   char=text.index(needle);token_offset=bisect_left(starts,char)
   positions.append(dict(message_id=mid,char_offset=char,token_offset=token_offset,fraction=token_offset/target))
  entry['locations']=positions
 return text,truth,dict(reference_tokens=count(tokenizer,text),distractor_messages=index,
                       critical_values=len(truth),critical_source_messages=2*len(truth),origin='synthetic_T0_replay')


def _write_sources(root,values):
 for name,text in values.items():
  path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(text,encoding='utf-8',newline='\n')


def prepare(output,tokenizer_path,seeds=PILOT_SEEDS,*,target=TARGET):
 from tokenizers import Tokenizer
 output=Path(output).resolve();tokenizer_path=Path(tokenizer_path).resolve()
 if output.exists():raise ValueError('Refuse to overwrite an existing campaign or results')
 if any(str(output).lower().startswith(p) for p in [r'c:\users\venya\omp-zones-work',r'e:\ozproof-20260926\context300k-httpx']):
  raise ValueError('Protected or active workspace is not a campaign destination')
 tokenizer=Tokenizer.from_file(str(tokenizer_path));output.mkdir(parents=True)
 public=output/'public';private=output/'evaluator-private';public.mkdir();private.mkdir()
 variants=[]
 for ordinal,seed in enumerate(seeds):
  variant='case-'+sha(f'variant:{seed}'.encode())[:12]
  visible=public/variant;hidden=private/variant;visible.mkdir();hidden.mkdir()
  c=configuration(seed);text,truth,counts=corpus(seed,tokenizer,target)
  from .context300k_evaluation import EVALUATOR, qualify_controls
  control=qualify_controls(seed)
  if not control['reference_pass'] or not control['all_defects_detected']:
   raise ValueError('Reference or negative control failed before model dispatch')
  (hidden/'evaluate.py').write_text(EVALUATOR,encoding='utf-8',newline='\n')
  write_json(hidden/'control-qualification.json',control)
  (visible/'history.txt').write_text(text,encoding='utf-8',newline='\n')
  _write_sources(visible/'workspace',sources(c,baseline=True));_write_sources(hidden/'reference',sources(c))
  tests_dir=visible/'workspace'/'tests';tests_dir.mkdir()
  test_source="import json\nfrom parcelgrid.legacy_io import read_rows\n\ndef test_blank_lines_and_order():\n    assert read_rows([json.dumps(dict(id=1)), ' ', json.dumps(dict(id=2))]) == [dict(id=1), dict(id=2)]\n"
  (tests_dir/'test_legacy.py').write_text(test_source,encoding='utf-8',newline='\n')
  # Freeze a portable source inventory now. The native adapter must later
  # construct/admit its real Git snapshot; a SHA256 inventory is NOT a Git tree.
  source_files={p.relative_to(visible/'workspace').as_posix():sha(p.read_bytes())
                for p in (visible/'workspace').rglob('*') if p.is_file()}
  source_commit=None
  source_tree=sha(canonical(source_files).encode('utf-8'))
  write_json(hidden/'initial-source-inventory.json',source_files)
  tasks=[]
  for task,module,deps,description in TASKS:
   tasks.append(dict(task_id=task,prerequisites=list(deps),source_paths=[f'parcelgrid/{module}.py'],
    instruction=description+' Preserve public signatures and T0 legacy_io. Resolve the approved contracts in history; report the values used and source message IDs. Add your own tests. No hidden evaluator access.',
    decision_keys=FACT_GROUPS[task],max_model_calls=20))
  write_json(visible/'tasks.json',dict(schema=SCHEMA,tasks=tasks,release='after_full_history_checkpoint',
   initial_task='T0',task0_status='SYNTHETIC_COMPLETED',no_oracle_packets=True))
  write_json(hidden/'oracle.json',dict(schema=SCHEMA,seed=seed,facts=truth,cases=cases(c,seed)))
  # Hidden source and labels are NEVER inside an agent mount or its Git objects.
  write_json(visible/'agent-contract.json',dict(schema=SCHEMA,history_sha256=sha(text.encode()),
   tools=['read','grep','glob','edit','write','approved_test'],network=False,
   available_files=['history.txt','tasks.json','workspace'],sealed_paths=['parcelgrid/legacy_io.py'],
   decision_report_format={'choices':[{'key':'one decision key','value':'typed value','sources':['message-id']}]}))
  variants.append(dict(variant=variant,phase='PILOT' if seed in PILOT_SEEDS else 'CONFIRMATORY',
   order=['A1','B4'] if ordinal%2==0 else ['B4','A1'],counts=counts,
   history_sha256=sha(text.encode()),oracle_sha256=sha((hidden/'oracle.json').read_bytes()),
   source_commit=source_commit,source_inventory_sha256=source_tree,git_snapshot_admitted=False))
  print('PREPARED',variant,counts,flush=True)
 plan=dict(schema=SCHEMA,status='PREPARED_NOT_EXECUTED',model_calls=0,dispatch_authorized=False,
  arms=ARMS,primary_pair=['A1','B4'],ablations=['B1','A4'],variants=variants,
  tokenizer=dict(path=str(tokenizer_path),sha256=sha(tokenizer_path.read_bytes()),
   meaning='exact count in the pinned reference tokenizer; not a provider-active-context claim'),
  primary_target=target,history_in_model_context_required=True,
  native_bindings=dict(product='existing TaskOwner + long_lived_sessions',benchmark='existing fast_zoning recorder/terminal classifier',
   scheduler='TaskOwner only',evaluator='existing protected test provider'),
  preflight_required=['same_exact_model_revision','model_tokenizer_capacity_and_active_checkpoint_receipt',
   'native_context_import_no_silent_truncation','TaskOwner_admission_for_source_and_session_roles',
   'same_tools_and_model_budgets','private_evaluator_not_mounted','provider_usage_accounting',
   'fresh_arm_workspaces_profiles_databases','explicit_dispatch_authorization'],
  protocol=dict(start='Both arms receive the same raw 300k checkpoint at t0; no prepared B fact packets.',
   accounting='Charge B routing/indexing/compaction/handoffs, retries, verification and final integration.',
   A_compaction='native default permitted after verified initial checkpoint; never disable to weaken A',
   warm_start='separate optional condition; charge history ingestion once to each arm and show incremental plus end-to-end totals',
   quality='8 fully accepted task groups + legacy regression; hidden tests are one workload, not independent replicates',
   speed='critical-path wall time to final accepted integrated source; not sum of worker durations',
   tokens='provider input/cache-write/cache-read/output/reasoning separately; unknown is null, not zero',
   routing='B must find and transfer facts itself; A may search the same entire archive',
   repeats='3 pilot seeds then preregistered 20 new paired seeds; no best-of reruns or early success stop',
   claim='No winner without actual paired measurements; savings are compared at equal accepted quality'))
 plan['preparer_sources']={p.name:sha(p.read_bytes()) for p in Path(__file__).parent.glob('context300k*.py')}
 write_json(output/'campaign.json',plan)
 profile={name:False for name in plan['preflight_required']}
 profile.update(model_id=None,model_revision=None,model_context_limit=None,model_tokenized_history_tokens=None,
  output_and_tools_reserve_tokens=32768,native_request_receipt_sha256=None,model_tokenizer_sha256=None,
  owner_admission_receipt_sha256=None,protected_evaluator_receipt_sha256=None,
  note='UNBOUND: not dispatch permission. Authenticate real owner/model receipts before execution.')
 write_json(output/'launch-profile.template.json',profile)
 write_json(output/'results.template.json',dict(status='NOT_EXECUTED',model_calls=0,pairs=[],winner=None))
 manifest={p.relative_to(output).as_posix():sha(p.read_bytes()) for p in output.rglob('*') if p.is_file()}
 write_json(output/'sealed-files.json',manifest)
 return plan


def verify(output):
 root=Path(output);manifest=json.loads((root/'sealed-files.json').read_text(encoding='utf-8'))
 errors=[]
 actual={p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file() and p.name!='sealed-files.json'}
 if actual!=set(manifest):raise ValueError('Unexpected or missing files; possible oracle leakage')
 for name,digest in manifest.items():
  path=root/name
  if not path.is_file() or sha(path.read_bytes())!=digest:errors.append(name)
 if errors:raise ValueError('Campaign file changed or missing: '+', '.join(errors[:8]))
 return dict(status='SEALED_PREPARATION_VALID',files=len(manifest),model_execution_verified=False)


def main(argv=None):
 parser=argparse.ArgumentParser(description='Prepare and seal a model-free 300k multi-zone A/B campaign')
 sub=parser.add_subparsers(dest='command',required=True)
 create=sub.add_parser('prepare');create.add_argument('--output',required=True);create.add_argument('--tokenizer',required=True)
 create.add_argument('--phase',choices=['pilot','confirmatory','all'],default='pilot')
 check=sub.add_parser('verify');check.add_argument('output')
 args=parser.parse_args(argv)
 if args.command=='verify':print(canonical(verify(args.output)));return 0
 seeds=PILOT_SEEDS if args.phase=='pilot' else CONFIRM_SEEDS if args.phase=='confirmatory' else (*PILOT_SEEDS,*CONFIRM_SEEDS)
 plan=prepare(args.output,args.tokenizer,seeds)
 print(canonical(dict(status=plan['status'],variants=len(plan['variants']),model_calls=0)))
 return 0

if __name__=='__main__':raise SystemExit(main())
