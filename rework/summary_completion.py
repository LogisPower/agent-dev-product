"""Deterministic final presentation for completed bounded count snapshots.

This does not claim that a planner covered every part of arbitrary user intent.
Discovery/read chains and mixed plans stay on the existing bounded path.
"""
FIELDS={
 'system_summary':{'total_memory_kib','available_memory_kib'},
 'service_summary':{'sampled','running','stopped','other'},
 'startup_summary':{'visible_entry_count'},
 'event_summary':{'sampled','critical','error','warning'}}

def completed_summary(actions,results):
    names=[a.tool for a in actions]
    if not names or len(names)!=len(set(names)) or len(names)!=len(results) or any(n not in FIELDS for n in names):return None
    paragraphs=[]
    for index,(name,r) in enumerate(zip(names,results),1):
        d=r.get('data',{})
        if not isinstance(d,dict):return None
        v=d.get('records')
        if r.get('tool')!=name or r.get('status')!='read' or r.get('effect')!='none' or d.get('status')!='read' or d.get('tool')!=name:return None
        if not isinstance(v,dict) or set(v)!=FIELDS[name] or any(type(x) is not int or not 0<=x<=2**53 for x in v.values()):return None
        if name=='service_summary':
            if v['sampled']!=v['running']+v['stopped']+v['other']:return None
            text=f"Visible services: {v['running']} running, {v['stopped']} stopped, {v['other']} in other states; {v['sampled']} total. A stopped service can be normal or demand-started. Counts alone do not establish PC health, resource pressure, malware or which service needs action."
        elif name=='system_summary':
            if v['available_memory_kib']>v['total_memory_kib']:return None
            text=f"OS-visible memory: {v['total_memory_kib']} KiB total; {v['available_memory_kib']} KiB available at observation. This is a memory snapshot, not commit, paging, CPU or memory-leak diagnosis."
        elif name=='startup_summary':
            text=f"Visible Win32_StartupCommand entries: {v['visible_entry_count']}. This excludes other startup mechanisms, scheduled tasks and service startup; the count does not identify unsafe entries or their performance impact."
        else:
            if v['sampled']>32 or v['sampled']!=v['critical']+v['error']+v['warning']:return None
            text=f"Recent System event sample: {v['critical']} critical, {v['error']} errors, {v['warning']} warnings; {v['sampled']} sampled. Coverage is at most 32 latest matching events in 24 hours, not the full event count. Messages were not read; counts alone do not establish a cause."
        stamp=d.get('observed_at') or r.get('observed_at')
        if not isinstance(stamp,str) or not stamp or len(stamp)>80:return None
        paragraphs.append(text+f" [T{index}] Observed: {stamp}.")
    answer='\n\n'.join(paragraphs)+'\n\nThese bounded read-only snapshots are the evidence collected. No settings or files were changed; broader diagnosis or other requested work is not established by these counts.'
    return answer,{'status':'deterministic_summary','evidence_ids':['T'+str(i+1) for i in range(len(results))],'claim_verification':'Validated count fields and identities; fixed coverage limitations. Not a general goal-completion guarantee.','additional_model_calls':0}
