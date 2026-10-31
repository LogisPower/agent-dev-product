"""Fixed-output evidence tool. No generated code execution or arbitrary paths."""
import hashlib,json,re
from pathlib import Path
from document_rag import snapshot,digest

def safe_directory(root,run,create=False):
    if not re.fullmatch('[a-f0-9]{32}',run):raise ValueError('Invalid run')
    root=Path(root).absolute()
    for part in (root,*root.parents):
        if part.is_symlink() or (hasattr(part,'is_junction') and part.is_junction()):raise ValueError('Linked artifact root')
    if create:root.mkdir(parents=True,exist_ok=True)
    target=root/run
    if target.is_symlink() or (hasattr(target,'is_junction') and target.is_junction()):raise ValueError('Linked artifact directory')
    return target

def verify(root,run,receipt,project,ids,loader,fingerprint):
    if digest(snapshot(loader,project,ids))!=fingerprint:raise ValueError('Source revision changed')
    path=safe_directory(root,run)/'evidence.json'
    if path.is_symlink() or path.stat().st_size>100000:raise ValueError('Invalid artifact')
    raw=path.read_bytes()
    if len(raw)!=receipt['bytes'] or hashlib.sha256(raw).hexdigest()!=receipt['sha256']:raise ValueError('Artifact differs from checked bytes')
    value=json.loads(raw)
    if value['project']!=project or value['source_fingerprint']!=fingerprint:raise ValueError('Artifact scope mismatch')
    rows={r['id']:r for r in snapshot(loader,project,ids)}
    for match in value['result']['matches']:
        source=rows[match['source_id']]
        if match['revision']!=source['revision'] or match['sha256']!=source['sha256'] or source['content'][match['start']:match['end']]!=match['text']:raise ValueError('Evidence quote mismatch')
    return {'bytes':'verified','source_revisions':'verified','quotes':'verified','answer_claims':'not_independently_proven'}

def save(root,run,project,ids,loader,fingerprint,result):
    if result.get('status')!='answered':raise ValueError('No supported answer to save')
    if digest(snapshot(loader,project,ids))!=fingerprint:raise ValueError('Source changed before tool action')
    value={'schema':1,'project':project,'run':run,'source_fingerprint':fingerprint,'result':result}
    raw=json.dumps(value,ensure_ascii=False,sort_keys=True,indent=2).encode()
    if len(raw)>100000:raise ValueError('Artifact size bound')
    target=safe_directory(root,run,True);target.mkdir(exist_ok=False)
    with (target/'evidence.json').open('xb') as f:f.write(raw)
    receipt={'file':'evidence.json','sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw),'tool':'save_selected_source_brief','generated_code_executed':False}
    receipt['verification']=verify(root,run,receipt,project,ids,loader,fingerprint)
    return receipt
