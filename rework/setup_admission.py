"""Conservative admission for one lightweight checklist write, not PC diagnosis.

Only called with server-collected evidence; no model-provided evidence parameter.
"""
import datetime,math,json

class AdmissionDenied(Exception):
    def __init__(self,decision):
        self.decision={**decision,'final':True,'effect':'none','boundary':'locked_prewrite'}
        super().__init__('Admission denied before filesystem write')

def json_safe_evidence(data):
    try:
        raw=json.dumps(data,allow_nan=False,ensure_ascii=False)
        if len(raw.encode('utf-8'))>30000:raise ValueError('size bound')
        return json.loads(raw)
    except (TypeError,ValueError,OverflowError):
        return {'records':[],'validation_error':{'code':'invalid_json_evidence','reason':'Non-finite, unsupported or oversized diagnostic payload rejected; raw values not persisted.'}}

POLICY={'id':'lightweight-window-v2.1','sample_count':5,'max_age_seconds':30,'min_available_mib':8192,'max_queue':1,'max_latency_seconds':0.05,'min_idle_percent':20,'pressure_rule':'last sample OR two consecutive OR three of five disk excursions','warmup_required':True,'idle_overshoot_tolerance_percentage_points':0.01}
SUFFIXES={'idle':'\\logicaldisk(c:)\\% idle time','read_latency':'\\logicaldisk(c:)\\avg. disk sec/read','write_latency':'\\logicaldisk(c:)\\avg. disk sec/write','queue':'\\logicaldisk(c:)\\current disk queue length','available':'\\memory\\available mbytes'}
def evaluate_window(data,now=None):
    """Shared lightweight admission only; not a model-load/stress-test budget.

    Accept only the fixed warmed collector contract. Retain every measured
    excursion. Any RAM breach fails immediately; disk pressure must have
    recovered by the final sample and not be repeated in the bounded window.
    """
    now=now or datetime.datetime.now(datetime.timezone.utc)
    reasons=[];observed=[];normalizations=[]
    try:
        if data.get('measurement')!={'version':2,'warmup_samples_discarded':1,'measured_samples':5,'interval_seconds':1}:
            raise ValueError('Warmed measurement contract required')
        rows=data['records']
        if not isinstance(rows,list) or len(rows)!=5:raise ValueError('five complete samples required')
        prior=None
        for row in rows:
            stamp=datetime.datetime.fromisoformat(row['timestamp'].replace('Z','+00:00'))
            if stamp.tzinfo is None or not 0<=(now-stamp).total_seconds()<=30:raise ValueError('stale or future sample')
            if prior is not None and not 0.75<=(stamp-prior).total_seconds()<=2:
                raise ValueError('unordered or nonrepresentative sample interval')
            prior=stamp;values={}
            for key,suffix in SUFFIXES.items():
                found=[c for c in row['counters'] if isinstance(c.get('Path'),str) and c['Path'].casefold().endswith(suffix)]
                if len(found)!=1:raise ValueError('missing or duplicate required counter')
                c=found[0];v=c.get('CookedValue')
                if type(c.get('Status')) is not int or c['Status']!=0 or type(v) not in (int,float) or not math.isfinite(v) or v<0:
                    raise ValueError('invalid counter')
                values[key]=v
            if values['idle']>100.01:raise ValueError('invalid idle percentage beyond 0.01 percentage-point tolerance')
            if values['idle']>100:
                normalizations.append({'sample_index':len(observed),'counter':'C: idle percent','raw':values['idle'],'normalized':100.0,'reason':'bounded percentage overshoot; not proof of physical idle above 100'})
                values['idle']=100.0
            if values['available']<8192:reasons.append('available RAM below unchanged 8 GiB reserve')
            observed.append(values)
        # A disk excursion is any original threshold breach, not just combined
        # metrics. Alternating queue/latency/activity pressure is still pressure.
        excursions=[v['queue']>1 or max(v['read_latency'],v['write_latency'])>0.05 or v['idle']<20 for v in observed]
        if excursions[-1]:reasons.append('disk excursion remains in final sample')
        if any(a and b for a,b in zip(excursions,excursions[1:])):reasons.append('consecutive disk pressure samples')
        if sum(excursions)>=3:reasons.append('disk pressure in at least three of five samples')
    except (KeyError,TypeError,ValueError,OverflowError,AttributeError) as e:
        return {'decision':'unknown','allowed':False,'reasons':[str(e)],'policy':POLICY,'healthy_pc_claim':False}
    return {'decision':'pause' if reasons else 'admit_lightweight_checklist','allowed':not reasons,'reasons':sorted(set(reasons)),
      'policy':POLICY,'healthy_pc_claim':False,'evidence':{'sample_count':5,'counter_normalizations':normalizations,'disk_excursion_indices':[i for i,x in enumerate(excursions) if x],
      'minimum_available_mib':min(v['available'] for v in observed),'final_disk_excursion':excursions[-1]},
      'scope':'One lightweight operation only. Short samples can miss stalls; no causal or virus verdict. Not model-load admission.'}

def assess(receipt,run,project,now=None):
    if not isinstance(receipt,dict) or receipt.get('actor')!={'initiated_by':'logis_dispatcher','run_id':run,'project_id':project} or receipt.get('tool')!='disk_activity':
        return {'decision':'unknown','allowed':False,'reasons':['origin binding or diagnostic tool invalid'],'policy':POLICY,'healthy_pc_claim':False}
    return evaluate_window(receipt.get('data'),now)

def execute(db,project,action,permissions,run):
    # Capture run identity before any host inspection. The actor label alone is
    # not proof: evidence and admission are persisted in this same scoped run.
    from psycopg.types.json import Jsonb
    def current():
        with db() as c:row=c.execute('SELECT status,payload FROM logis_candidate.runs WHERE id=%s AND project_id=%s',(run,project)).fetchone()
        return bool(row and row['status']=='running' and not row['payload'].get('cancel_requested'))
    if project not in permissions.get('projects',[]) or not permissions.get('write'):raise PermissionError('Approved project write scope required')
    if not current():raise ValueError('Setup origin inactive; no diagnostics or effect')
    from setup_scope import request_allowed
    if not request_allowed(permissions) and permissions.get('disk_read') is not True:
        return {'status':'permission_needed','effect':'none','missing_scope':'setup_activity_read','diagnostics_performed':False,'admission':{'allowed':False},'notice':'No PC check or write occurred.'}
    from disk_diagnostics import collect
    data=json_safe_evidence(collect('disk_activity',permissions))
    receipt={'tool':'disk_activity','data':data,'actor':{'initiated_by':'logis_dispatcher','run_id':run,'project_id':project}}
    decision=assess(receipt,run,project)
    with db(False) as c:
        row=c.execute('SELECT status,payload FROM logis_candidate.runs WHERE id=%s AND project_id=%s FOR UPDATE',(run,project)).fetchone()
        if not row or row['status']!='running' or row['payload'].get('cancel_requested'):raise ValueError('Setup canceled before admission commit; no file effect')
        c.execute('UPDATE logis_candidate.runs SET payload=payload || %s WHERE id=%s AND project_id=%s',(Jsonb({'setup_diagnostic':receipt,'setup_admission':decision}),run,project))
    if not decision['allowed']:return {'status':'paused','effect':'none','diagnostics_performed':True,'diagnostic':receipt,'admission':decision,'notice':'Setup paused; no file effect. Evidence does not establish a root cause.'}
    # Recheck sample age immediately before entering the existing effect gate.
    latest=assess(receipt,run,project)
    if not latest['allowed'] or not current():
        latest={**latest,'allowed':False,'final':True,'effect':'none','boundary':'prewrite_recheck'}
        with db(False) as c:c.execute('UPDATE logis_candidate.runs SET payload=payload || %s WHERE id=%s AND project_id=%s',(Jsonb({'setup_admission':latest}),run,project))
        return {'status':'paused','effect':'none','admission':latest,'notice':'Evidence expired or task stopped before effect; no file write.'}
    from checklist_addon import execute as create
    def at_effect():
        if not request_allowed(permissions) and permissions.get('disk_read') is not True:
            raise AdmissionDenied({'allowed':False,'decision':'permission_revoked','reasons':['Setup-health grant no longer valid at effect boundary'],'healthy_pc_claim':False})
        checked=assess(receipt,run,project)
        if not checked['allowed']:raise AdmissionDenied(checked)
    artifact=create(db,project,action,permissions,run,admission_check=at_effect)
    if artifact.get('status')=='prewrite_denied':
        return {'status':'paused','effect':'none','diagnostics_performed':True,'diagnostic':receipt,'admission':artifact['admission'],'notice':'Final admission denied inside the effect lock; no file write occurred.'}
    return {'status':'verified','effect':'workspace_file','diagnostics_performed':True,'diagnostic':receipt,'admission':latest,'artifact':artifact,
      'notice':'Logis collected bounded counters, admitted one lightweight write and verified its bytes. This is not a full PC health assessment.'}
