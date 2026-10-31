"""Narrow explicit read optimizations. Other intents retain typed planning."""
import re,hashlib

def workspace_read_request(text):
    match=re.fullmatch(r'(?i)(?:please\s+)?(?:read|show)\s+([A-Za-z0-9_][A-Za-z0-9_./-]{0,178})\s+(?:from|in)\s+(?:this|the)\s+(?:project\s+)?workspace(?:\s+and\s+(?:show|display)\s+(?:its|the)\s+contents)?[.!]?',text.strip())
    if not match:return None
    path=match[1]
    if any(x in ('','..','.') or x.casefold()=='.logis' for x in path.split('/')):return None
    return path

def network_denied(text):
    return bool(re.search(r"(?i)\b(?:do not|don't|dont|never|must not|should not|cannot|can't)\s+(?:(?:use|perform|do|access)\s+)?(?:any\s+)?(?:web|internet|online|network|search|browse|fetch)\b|\b(?:offline only|without (?:the )?(?:internet|web|network)|no (?:web|online|internet|network) (?:access|search|requests))\b",text))

def public_research_request(text):
    if network_denied(text):return None
    t=text.strip()
    if re.search(r'[.!?]\s+\w|["\'`;:\n]',t):return None
    parts=re.split(r'(?i)\s+and\s+(?=explain\b|summarize\b)',t,maxsplit=1)
    topic=parts[0]
    excluded=r'(?i)\b(?:and|or|but|then|if|unless|after|before|not|no|never|without|delete|create|write|edit|move|execute|run|install|save|remember|forget|send|upload)\b'
    if re.search(excluded,topic):return None
    if len(parts)==2 and re.search(excluded,parts[1]):return None
    if not re.fullmatch(r'(?i)(?:please\s+)?find\s+(?:the\s+)?official\s+[A-Za-z0-9 ._/-]{1,100}\s+(?:documentation|docs)(?:\s+(?:about|on|explaining|for)\s+[A-Za-z0-9 ._/-]{1,120})?[.!?]?',topic):return None
    if len(parts)==2 and not re.fullmatch(r'(?i)(?:explain|summarize)\s+[A-Za-z0-9 ,._/-]{1,160}[.!?]?',parts[1]):return None
    return t

def completed_read(text,actions,results):
    path=workspace_read_request(text)
    if not path or len(actions)!=1 or actions[0].tool!='workspace_read' or actions[0].path!=path or len(results)!=1:return None
    r=results[0];d=r.get('data',{})
    if r.get('tool')!='workspace_read' or r.get('status')!='read' or r.get('effect')!='none' or not isinstance(d,dict) or d.get('path')!=path:return None
    content=d.get('content')
    if not isinstance(content,str):return None
    raw=content.encode('utf-8')
    if type(d.get('bytes')) is not int or len(raw)!=d['bytes'] or hashlib.sha256(raw).hexdigest()!=d.get('sha256'):return None
    if len(content)>32000:
        return 'The requested file was read, but exceeds the bounded display size. Its complete receipt remains available; narrow the request. No content was silently truncated.',{'status':'display_limit','evidence_ids':['T1'],'additional_model_calls':0}
    # Indentation presents inert quoted source, including embedded backticks.
    answer=f"Contents of {path} [T1] ({len(raw)} bytes; SHA-256 {d['sha256']}):\n\n"+'\n'.join('    '+line for line in content.split('\n'))+'\n\nFile text is source data; no instructions in it were executed.'
    return answer,{'status':'deterministic_file_display','evidence_ids':['T1'],'additional_model_calls':0,'claim_verification':'Exact UTF-8 bytes/hash checked against read receipt; not interpretation or execution.'}


def mixed_memory_web(text):
    """Conservative compound-command boundary, not a general intent parser."""
    if not re.match(r'(?i)^\s*(?:please\s+)?(?:remember|recall|correct|forget|what do you remember about)\b',text):return False
    return bool(re.search(r'(?i)(?:\b(?:and|then|but|also)\s+|[;.\n]\s*)(?:please\s+)?(?:(?:do not|don.t|never)\s+)?(?:search\b|browse\b|look up\b|fetch\b|(?:read|summarize)\s+https?://)',text))
