"""Fixed-template workspace addon, never arbitrary generated-code execution."""
import html,re,hashlib
from types import SimpleNamespace
VERSION='checklist-static-v1'

def specification(path,title,text):
    from workspace_files import relative
    relative(path)
    if not path.endswith('.html'):raise ValueError('Checklist path must end in .html')
    if not isinstance(title,str) or not 1<=len(title.strip())<=120:raise ValueError('Title must be 1-120 characters')
    if not isinstance(text,str):raise ValueError('Checklist items must be text')
    items=text.splitlines()
    if not 1<=len(items)<=12 or any(not x.strip() or len(x)>160 for x in items):raise ValueError('Use 1-12 nonempty items, each at most160 characters')
    if any(ord(c)<32 and c not in '\n\r\t' for c in title+text):raise ValueError('Control character rejected')
    return title.strip(),[x.strip() for x in items]

def validate_request(action,original):
    title,items=specification(action.path,action.query,action.text)
    from setup_intent import parse_setup_request
    setup=parse_setup_request(original)
    if setup is not None:
        if getattr(action,'tool',None)!='setup_checklist':raise ValueError('Health-conditioned creation requires the setup admission gate')
        if any(getattr(action,k,None)!=value for k,value in setup.items()):raise ValueError('Artifact fields must exactly match the parsed user request')
        return
    # Match the object of the requested action, not merely a creation verb.
    # "Create a plan for a checklist" requests a plan and is not file authority.
    direct=re.match(r'(?i)^\s*(?:(?:please|can you|could you)\s+)?(?:create|make|build)\s+(?:me\s+)?(?:(?:a|an|the)\s+)?(?:(?:offline|html)\s+){0,2}checklist\b',original)
    if not direct:raise ValueError('Direct checklist creation required; plans and proposals do not authorize files')
    if action.path not in original:raise ValueError('Explicit checklist filename required')
    if title not in original or any(item not in original for item in items):raise ValueError('Title and every item must be exact user-request excerpts')
    if re.search(r'(?i)\b(?:do not|don.t|never|hypothetical|pretend|quoted|page says)\b',original):raise ValueError('Negated or quoted instructions cannot authorize creation')
    # Conservative ambiguity guard applies before extracting model-selected
    # fields: a planner must not hide "if I approve" inside a title/item.
    remainder=original[direct.end():]
    if re.search(r'(?i)\b(?:if|unless|when|after|before|later|tomorrow|eventually|plan|proposal|propose|planning|future|would|should|might|could)\b',remainder):
        raise ValueError('Conditional/future/planning request requires clarification; no file authority')

def render(path,title,text):
    title,items=specification(path,title,text)
    rows=''.join('<li><label><input type="checkbox"> '+html.escape(item)+'</label></li>' for item in items)
    value='<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'; form-action \'none\'; base-uri \'none\'"><title>'+html.escape(title)+'</title><style>body{font:18px system-ui;max-width:48rem;margin:3rem auto;padding:0 1rem;background:#f8fafc;color:#172033}li{list-style:none;margin:1rem 0}input{width:1.2rem;height:1.2rem}label{cursor:pointer}small{color:#334155}</style></head><body><h1>'+html.escape(title)+'</h1><ul>'+rows+'</ul><small>Local checklist. Checkmarks are not saved by this file. No scripts, network calls or automatic actions.</small></body></html>'
    if len(value.encode())>12000:raise ValueError('Rendered addon bound')
    return value

def execute(db,project,action,permissions,run,admission_check=None):
    # This is a constrained renderer. The policy layer already validates original
    # user excerpts; the workspace adapter independently enforces scope and run.
    value=render(action.path,action.query,action.text)
    from workspace_facade import execute as effect,workspace
    delegated=SimpleNamespace(tool='workspace_create',path=action.path,text=value,expected_sha256='',destination='')
    mutation=effect(db,project,delegated,permissions,run,admission_check=admission_check) if admission_check is not None else effect(db,project,delegated,permissions,run)
    if mutation.get('status')=='prewrite_denied':return mutation
    # Read back through the same pinned-path adapter, not a generic file open.
    observed=workspace(project,permissions).read(action.path)
    expected=hashlib.sha256(value.encode()).hexdigest()
    if observed.get('sha256')!=expected or observed.get('content')!=value:
        raise ValueError('Addon effect needs reconciliation: saved bytes differ; no repeat or overwrite')
    return {'template':VERSION,'path':action.path,'sha256':expected,'bytes':len(value.encode()),
      'mutation':mutation,'verification':'exact rendered bytes independently read back; browser behavior not tested',
      'code_executed':False,'network_calls':False,'persistent_checkmarks':False,
      'automatic_promotion':False,'rollback':'Original file never overwritten; created file remains journaled. Any later removal/move needs its own authorized action.'}
