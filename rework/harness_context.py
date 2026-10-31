"""Pinned selective context; no discovery, execution, grants or external reads."""
import hashlib,json,re
from pathlib import Path
ROOT=Path(__file__).parent/'harness-context-v1'
CORE=('core/persona.md','core/authority.md')
SKILLS={'intent':'skills/intent-capabilities.md','web':'skills/web-research.md','memory':'skills/memory.md','clock':'skills/clock.md'}
# Pinned by release preparation; manifest integrity is checked independently of contents.
MANIFEST_HASH='eb96c99f786d4d5d1de26967ac7d4000f698fcf79b8d93bcbabcc0e786bc2187'
def assemble(skill='intent',root=None):
    root=Path(root or ROOT); raw=(root/'manifest.json').read_bytes()
    if hashlib.sha256(raw).hexdigest()!=MANIFEST_HASH:raise ValueError('Harness context manifest integrity failed')
    manifest=json.loads(raw);names=CORE+(SKILLS[skill],);parts=[];receipt=[]
    for name in names:
        path=root/name
        if any(p.is_symlink() or p.is_junction() for p in [root,path,*list(path.parents)[:len(Path(name).parts)-1]]):raise ValueError('Harness context links are not permitted')
        if not path.resolve().is_relative_to(root.resolve()):raise ValueError('Harness context escaped root')
        data=path.read_bytes();entry=manifest['files'][name]
        if len(data)>9000 or len(data)!=entry['bytes'] or hashlib.sha256(data).hexdigest()!=entry['sha256']:raise ValueError('Harness context content integrity failed')
        text=data.decode('utf-8');text=re.sub(r'^Status: STAGED DESIGN.*\n','',text,flags=re.M)
        parts.append(text);receipt.append({'path':name,'sha256':entry['sha256'],'bytes':len(data)})
    combined='\n\n'.join(parts)
    if len(combined)>12000:raise ValueError('Harness selected context budget exceeded')
    return combined,{'version':'1','selected':receipt,'characters':len(combined),'token_estimate':'characters/4 only','automatic_promotion':False}

def snapshot(app,permissions=None):
    web=callable(getattr(app.state,'intent_research',None))
    from tool_catalog import catalog
    return {'tools':catalog(app,permissions),'scope':'current authenticated project; grants rechecked at dispatch','web':{'registered':web,'availability':'configured_not_probed' if web else 'unavailable'},'clock':{'registered':True,'availability':'host_clock'},'memory':{'registered':True,'availability':'canonical_project_records; explicit writes only'},'evidence_task':{'registered':callable(getattr(app.state,'document_submit',None))},'mcp':{'registered':catalog(app,permissions)['mcp_clock']['registered'],'availability':'configured_not_probed; bounded local clock only'},'paperclip':{'registered':False,'availability':'not connected to this dispatcher'},'automatic_improvement':False}

def capability_query(text):
    return bool(re.fullmatch(r"\s*(?:(?:can|could|are) you|do you (?:have|support))\s+(?:(?:able to|access to)\s+)?(?:search (?:the )?(?:web|internet)|browse(?: (?:the )?(?:web|internet))?|use (?:the )?(?:web|internet)|web (?:access|search)|internet access)(?:\s+(?:now|yet|today))?[?.!]*\s*",text,re.I))

def capability_answer(state):
    if state['web']['registered']:
        return 'Web search and public page reading are connected to this chat. I have not made a network request for this capability check, so current provider availability is not yet verified. What would you like me to search for?'
    return 'Web search is unavailable in this chat runtime. No search was attempted. Local clock and explicit project memory operations remain separate capabilities.'
