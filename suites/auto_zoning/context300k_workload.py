# Seeded multi-component workload. Reference patches and expected outputs are private.
from __future__ import annotations
import copy
from datetime import date, timedelta
import random

TASKS = (
 ('T1','pricing',(),'Implement quote(subtotal_cents, cohort) with the agreed discount, cap and tax semantics.'),
 ('T2','inventory',(),'Implement available(initial, events, now_ms): reservations, expiry, duplicates and tenant isolation.'),
 ('T3','events',(),'Implement normalize(raw): current aliases, timestamp units and exact event identities.'),
 ('T4','shipping',(),'Implement ship_date(placed_at, service): timezone, cutoff and business-day delivery.'),
 ('T5','privacy',(),'Implement redact(value): recursive masking without mutation or loss of identifiers.'),
 ('T6','retry',(),'Implement retry_delay(status, retry_index, retry_after_ms=None) using the current retry policy.'),
 ('T7','checkout',('T1','T2','T4','T5'),'Implement checkout(order, stock, placed_at): combine price, quantity, tenant stock, shipping and safe metadata.'),
 ('T8','recovery',('T2','T3','T6'),'Implement recover(initial, raw_events, now_ms): logical ordering, duplicate conflicts, stock replay and retries.'),
)


def configuration(seed):
 r=random.Random(seed)
 return dict(discount_bps=r.choice([750,1250,1750]),discount_cap=r.choice([975,1375,1875]),
  tax_bps=r.choice([725,825,925]),cohort=r.choice(['partner','trade','member']),
  ttl_ms=r.choice([90000,120000,180000]),default_tenant='tenant-'+str(r.randrange(30,99)),
  order_field=r.choice(['purchase_ref','booking_ref','order_ref']),timestamp_unit='milliseconds',
  cancellation_alias=r.choice(['voided','withdrawn','cancelled']),utc_offset=r.choice([-5,2,3]),
  cutoff_hour=r.choice([14,15,16]),standard_days=r.choice([2,3]),express_days=1,weekend=[5,6],
  secret_fields=['authorization','password','access_token',r.choice(['api_key','client_secret','session_key'])],
  mask='[REDACTED]',retry_statuses=[429,502,503],retry_base_ms=r.choice([125,250,400]),
  retry_cap_ms=r.choice([4000,8000]),retry_limit=r.choice([3,4,5]),expiry_inclusive=True,
  dedupe_scope=['tenant','event_id'],rounding='half_up',event_order='sequence_then_event_id',
  quantity_type='strict_positive_int',duplicate_conflict='raise_value_error',checkout_stock_key='tenant/sku')

FACT_GROUPS={
 'T1':['discount_bps','discount_cap','tax_bps','cohort','rounding'],
 'T2':['ttl_ms','expiry_inclusive','dedupe_scope','quantity_type','duplicate_conflict'],
 'T3':['default_tenant','order_field','timestamp_unit','cancellation_alias'],
 'T4':['utc_offset','cutoff_hour','standard_days','express_days','weekend'],
 'T5':['secret_fields','mask'], 'T6':['retry_statuses','retry_base_ms','retry_cap_ms','retry_limit'],
 'T7':['checkout_stock_key','quantity_type','rounding'],
 'T8':['event_order','dedupe_scope','duplicate_conflict'],
}


def sources(c,baseline=False):
 cfg=copy.deepcopy(c)
 if baseline:
  cfg.update(discount_bps=0,tax_bps=0,ttl_ms=60000,default_tenant='legacy',order_field='id',
             cutoff_hour=23,standard_days=1,secret_fields=['password'],retry_statuses=[500])
 templates={
 'pricing.py':'''DISCOUNT={discount_bps}\nCAP={discount_cap}\nTAX={tax_bps}\nCOHORT={cohort!r}

def quote(subtotal_cents, cohort):
    if type(subtotal_cents) is not int or subtotal_cents < 0:
        raise ValueError('nonnegative integer cents required')
    discount = min(CAP,(subtotal_cents*DISCOUNT+5000)//10000) if cohort == COHORT else 0
    net = subtotal_cents-discount
    tax = (net*TAX+5000)//10000
    return dict(subtotal_cents=subtotal_cents,discount_cents=discount,tax_cents=tax,total_cents=net+tax)
''',
 'inventory.py':'''TTL={ttl_ms}

def available(initial, events, now_ms):
    if type(now_ms) is not int:
        raise ValueError('integer clock required')
    quantities, seen, holds = dict(initial), dict(), dict()
    for e in events:
        key = (e['tenant'],e['event_id'])
        if key in seen:
            if seen[key] != e:
                raise ValueError('conflicting duplicate')
            continue
        seen[key] = dict(e)
        stock_key = e['tenant']+'/'+e['sku']
        reservation = (e['tenant'],e['reservation_id'])
        if e['kind'] == 'reserve':
            qty = e['qty']
            if type(qty) is not int or qty <= 0:
                raise ValueError('positive integer quantity required')
            if reservation in holds:
                raise ValueError('reservation already exists')
            holds[reservation] = (stock_key,qty,e['at_ms']+TTL)
        elif e['kind'] == 'release':
            holds.pop(reservation,None)
        else:
            raise ValueError('unknown stock event')
    for stock_key,qty,expires in holds.values():
        if now_ms < expires:
            quantities[stock_key] = quantities.get(stock_key,0)-qty
            if quantities[stock_key] < 0:
                raise ValueError('oversold')
    return quantities
''',
 'events.py':'''DEFAULT_TENANT={default_tenant!r}\nORDER_FIELD={order_field!r}\nCANCEL_ALIAS={cancellation_alias!r}

def normalize(raw):
    tenant = raw.get('tenant',DEFAULT_TENANT)
    order_id = raw.get(ORDER_FIELD,raw.get('order_id'))
    for value in (tenant,order_id,raw.get('event_id')):
        if type(value) is not str or not value:
            raise ValueError('nonempty identity required')
    at_ms, sequence = raw['at_ms'],raw['sequence']
    if type(at_ms) is not int or type(sequence) is not int or sequence < 0:
        raise ValueError('integer time and sequence required')
    kind = 'release' if raw['kind'] == CANCEL_ALIAS else raw['kind']
    if kind not in ('reserve','release','delivery_failed'):
        raise ValueError('unknown event kind')
    result = dict(raw)
    result.update(tenant=tenant,order_id=order_id,kind=kind,at_ms=at_ms,sequence=sequence)
    return result
''',
 'shipping.py':'''from datetime import datetime,timedelta,timezone\nOFFSET={utc_offset}\nCUTOFF={cutoff_hour}\nSTANDARD={standard_days}\nEXPRESS={express_days}\nWEEKEND={weekend!r}

def ship_date(placed_at, service):
    instant = datetime.fromisoformat(placed_at)
    if instant.tzinfo is None or service not in ('standard','express'):
        raise ValueError('aware timestamp and known service required')
    local = instant.astimezone(timezone(timedelta(hours=OFFSET)))
    day = local.date()+timedelta(days=int(local.hour>=CUTOFF))
    while day.weekday() in WEEKEND:
        day+=timedelta(days=1)
    left = EXPRESS if service=='express' else STANDARD
    while left:
        day+=timedelta(days=1)
        if day.weekday() not in WEEKEND:
            left-=1
    return day.isoformat()
''',
 'privacy.py':'''import copy\nFIELDS={secret_fields!r}\nMASK={mask!r}

def redact(value):
    if isinstance(value,dict):
        return dict((k,MASK if isinstance(k,str) and k.casefold() in FIELDS else redact(v)) for k,v in value.items())
    if isinstance(value,list):
        return [redact(v) for v in value]
    return copy.deepcopy(value)
''',
 'retry.py':'''STATUSES={retry_statuses!r}\nBASE={retry_base_ms}\nCAP={retry_cap_ms}\nLIMIT={retry_limit}

def retry_delay(status,retry_index,retry_after_ms=None):
    if type(retry_index) is not int or retry_index<0:
        raise ValueError('nonnegative retry index required')
    if retry_after_ms is not None and (type(retry_after_ms) is not int or retry_after_ms<0):
        raise ValueError('nonnegative millisecond delay required')
    if status not in STATUSES or retry_index>=LIMIT:
        return None
    delay=min(CAP,BASE*2**retry_index)
    return delay if retry_after_ms is None else min(CAP,max(delay,retry_after_ms))
''',
 'checkout.py':'''from .pricing import quote\nfrom .shipping import ship_date\nfrom .privacy import redact

def checkout(order,stock,placed_at):
    qty=order['qty']
    if type(qty) is not int or qty<=0:
        raise ValueError('positive integer quantity required')
    key=order['tenant']+'/'+order['sku']
    if stock.get(key,0)<qty:
        raise ValueError('insufficient stock')
    result=quote(order['unit_cents']*qty,order['cohort'])
    result.update(order_id=order['order_id'],ship_date=ship_date(placed_at,order['service']),metadata=redact(order.get('metadata',dict())))
    return result
''',
 'recovery.py':'''from .events import normalize\nfrom .inventory import available\nfrom .retry import retry_delay

def recover(initial,raw_events,now_ms):
    events=[normalize(raw) for raw in raw_events]
    events.sort(key=lambda e:(e['sequence'],e['event_id']))
    seen,stocks,retries=dict(),[],[]
    for e in events:
        key=(e['tenant'],e['event_id'])
        if key in seen:
            if seen[key]!=e:
                raise ValueError('conflicting duplicate')
            continue
        seen[key]=e
        if e['kind']=='delivery_failed':
            delay=retry_delay(e['status'],e['retry_index'],e.get('retry_after_ms'))
            if delay is not None:
                retries.append(dict(tenant=e['tenant'],order_id=e['order_id'],delay_ms=delay))
        else:
            stocks.append(e)
    return dict(stock=available(initial,stocks,now_ms),retries=retries)
'''}
 result={'parcelgrid/'+name:text.format(**cfg) for name,text in templates.items()}
 result['parcelgrid/__init__.py']='"ParcelGrid staged order processing."\n'
 result['parcelgrid/legacy_io.py']='import json\n\ndef read_rows(lines):\n    return [json.loads(line) for line in lines if line.strip()]\n'
 if baseline:
  result['parcelgrid/checkout.py']=result['parcelgrid/checkout.py'].replace("key=order['tenant']+'/'+order['sku']","key=order['sku']")
  result['parcelgrid/recovery.py']=result['parcelgrid/recovery.py'].replace("events.sort(key=lambda e:(e['sequence'],e['event_id']))","events.sort(key=lambda e:e['at_ms'])").replace("key=(e['tenant'],e['event_id'])","key=e['event_id']")
  result['parcelgrid/pricing.py']=result['parcelgrid/pricing.py'].replace('type(subtotal_cents) is not int','not isinstance(subtotal_cents,int)').replace('tax = (net*TAX+5000)//10000','tax = round(subtotal_cents*TAX/10000)')
  result['parcelgrid/inventory.py']=result['parcelgrid/inventory.py'].replace("key = (e['tenant'],e['event_id'])","key = e['event_id']").replace('if now_ms < expires:','if now_ms <= expires:')
  result['parcelgrid/events.py']=result['parcelgrid/events.py'].replace('order_id=order_id,kind=kind','order_id=order_id.lower(),kind=kind').replace('at_ms=at_ms,sequence=sequence','at_ms=at_ms//1000,sequence=sequence')
  result['parcelgrid/shipping.py']=result['parcelgrid/shipping.py'].replace('local.hour>=CUTOFF','local.hour>CUTOFF')
  result['parcelgrid/privacy.py']=result['parcelgrid/privacy.py'].replace('return [redact(v) for v in value]','return value')
  result['parcelgrid/retry.py']=result['parcelgrid/retry.py'].replace('min(CAP,max(delay,retry_after_ms))','min(CAP,delay+retry_after_ms*1000)')
  result['parcelgrid/checkout.py']=result['parcelgrid/checkout.py'].replace("quote(order['unit_cents']*qty,order['cohort'])","quote(order['unit_cents'],order['cohort'])")
 return result


def cases(c,seed):
 # Concrete input/output oracle is constructed without running reference source.
 rows=[]
 def add(task,fn,args,expected=None,error=None):
  rows.append(dict(case_id=f'{task}-{sum(r["task_id"]==task for r in rows):03}',task_id=task,
                   function=fn,args=args,expected=expected,error=error,assert_inputs_unchanged=True))
 def money(n,cohort):
  d=min(c['discount_cap'],(n*c['discount_bps']+5000)//10000) if cohort==c['cohort'] else 0
  tax=((n-d)*c['tax_bps']+5000)//10000
  return dict(subtotal_cents=n,discount_cents=d,tax_cents=tax,total_cents=n-d+tax)
 for n in [0,1,7,20,49,50,60,99,200,333,600,999,1001,10000,10001,12345,123457]:
  for cohort in [c['cohort'],'guest']:add('T1','pricing.quote',[n,cohort],money(n,cohort))
 for invalid in [-1,True,1.1,'100']:add('T1','pricing.quote',[invalid,c['cohort']],error='ValueError')
 def hold(tenant='a',eid='r1',rid='h1',at=1000,qty=3):
  return dict(tenant=tenant,event_id=eid,reservation_id=rid,sku='S',kind='reserve',at_ms=at,qty=qty)
 for qty in [1,3,7]:
  e=hold(qty=qty)
  for now in [1000,1000+c['ttl_ms']-1,1000+c['ttl_ms'],1000+c['ttl_ms']+1]:
   add('T2','inventory.available',[{'a/S':10},[e],now],{'a/S':10-qty if now<1000+c['ttl_ms'] else 10})
 a,b=hold(),hold(tenant='b');release=dict(a,event_id='release',kind='release')
 add('T2','inventory.available',[{'a/S':10,'b/S':20},[a,b,a],1100],{'a/S':7,'b/S':17})
 add('T2','inventory.available',[{'a/S':10},[a,release],1100],{'a/S':10})
 add('T2','inventory.available',[{'a/S':10},[a,dict(a,qty=4)],1100],error='ValueError')
 for qty in [True,0,-1,11]:add('T2','inventory.available',[{'a/S':10},[hold(qty=qty)],1100],error='ValueError')
 for eid in ['ID-a','id-A','opaque-017']:
  raw={c['order_field']:'correct','order_id':'obsolete','event_id':eid,'at_ms':1735689600001,'sequence':4,'kind':c['cancellation_alias']}
  add('T3','events.normalize',[raw],dict(raw,tenant=c['default_tenant'],order_id='correct',kind='release'))
 for k,v in [('event_id',''),('sequence',True),('at_ms',1.5),('kind','unrecognized')]:
  raw=dict(order_id='o',tenant='t',event_id='e',at_ms=1000,sequence=1,kind='reserve');raw[k]=v
  add('T3','events.normalize',[raw],error='ValueError')
 def day_after(day,hour,service):
  day+=timedelta(days=int(hour>=c['cutoff_hour']))
  while day.weekday() in (5,6):day+=timedelta(days=1)
  for _ in range(c['express_days'] if service=='express' else c['standard_days']):
   day+=timedelta(days=1)
   while day.weekday() in (5,6):day+=timedelta(days=1)
  return day.isoformat()
 offset=f'{c["utc_offset"]:+03}:00'
 for day in [date(2025,1,2),date(2025,1,3),date(2025,1,4),date(2025,1,5)]:
  for hour in [c['cutoff_hour']-1,c['cutoff_hour'],23]:
   for service in ['standard','express']:add('T4','shipping.ship_date',[f'{day}T{hour:02}:00:00{offset}',service],day_after(day,hour,service))
 add('T4','shipping.ship_date',['2025-01-02T12:00:00','express'],error='ValueError')
 for k in c['secret_fields']:
  value={'nested':[{'Order_ID':'KeepCase',k.upper():'secret','token_count':7}],'order_id':'abc'}
  add('T5','privacy.redact',[value],{'nested':[{'Order_ID':'KeepCase',k.upper():c['mask'],'token_count':7}],'order_id':'abc'})
 add('T5','privacy.redact',[[None,1,True,'abc']],[None,1,True,'abc'])
 for status in [200,400,401,404,429,500,502,503]:
  for idx in [0,1,c['retry_limit']-1,c['retry_limit']]:
   expected=min(c['retry_cap_ms'],c['retry_base_ms']*2**idx) if status in c['retry_statuses'] and idx<c['retry_limit'] else None
   add('T6','retry.retry_delay',[status,idx],expected)
 for after in [0,2500,c['retry_cap_ms']*2]:add('T6','retry.retry_delay',[429,0,after],min(c['retry_cap_ms'],max(c['retry_base_ms'],after)))
 for idx in [-1,True]:add('T6','retry.retry_delay',[429,idx],error='ValueError')
 for qty in [1,3,7]:
  order=dict(tenant='a',sku='S',qty=qty,unit_cents=1999,cohort=c['cohort'],order_id='O',service='express',metadata={c['secret_fields'][-1]:'s','order_id':'O'})
  stamp=f'2025-01-03T{c["cutoff_hour"]:02}:00:00{offset}'
  expected=money(1999*qty,c['cohort']);expected.update(order_id='O',ship_date=day_after(date(2025,1,3),c['cutoff_hour'],'express'),metadata={c['secret_fields'][-1]:c['mask'],'order_id':'O'})
  add('T7','checkout.checkout',[order,{'a/S':10,'S':0},stamp],expected)
  add('T7','checkout.checkout',[order,{'other/S':10,'S':10},stamp],error='ValueError')
 def raw(e,seq,at=None):return dict(e,order_id='O',sequence=seq,at_ms=e['at_ms'] if at is None else at)
 reserve=raw(hold(),1,2000);rel=raw(dict(release,kind=c['cancellation_alias']),2,1000)
 retry=dict(tenant='b',order_id='O',event_id='fail',at_ms=999,sequence=3,kind='delivery_failed',status=429,retry_index=0,retry_after_ms=0)
 expected=dict(stock={'a/S':10,'b/S':10},retries=[dict(tenant='b',order_id='O',delay_ms=c['retry_base_ms'])])
 from itertools import permutations
 for events in permutations([reserve,rel,retry]):add('T8','recovery.recover',[{'a/S':10,'b/S':10},list(events)+[reserve],3000],expected)
 add('T8','recovery.recover',[{'a/S':10,'b/S':10},[raw(hold('a'),1),raw(hold('b'),2)],2000],dict(stock={'a/S':7,'b/S':7},retries=[]))
 add('T8','recovery.recover',[{'a/S':10},[reserve,dict(reserve,qty=8)],3000],error='ValueError')
 random.Random(seed+10000).shuffle(rows)
 return rows
