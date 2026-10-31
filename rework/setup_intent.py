"""Bounded present-action grammar. No authority inferred by the model.

Recognizes health-conditioned fixed checklists, not arbitrary conditional commands.
Unknown language stays on the existing clarification/validation path. Matching
does not confer workspace or telemetry grants; runtime gates still enforce both.
"""
import re

HEALTH = r'(?:the\s+)?(?:bounded\s+)?(?:C:\s*(?:activity|disk)\s+and\s+RAM\s+checks|PC\s+health\s+checks|setup[ -]health\s+checks)\s+(?:are\s+safe|pass)'
PREFIX = r'(?:Check whether this PC can safely handle one small setup write right now|Check (?:the )?(?:PC|setup)[ -]health|Check C: activity and RAM)[.!]\s*'
FAILURE = r'(?:\s*If (?:the )?(?:evidence|checks) (?:is|are) (?:unsafe or unavailable|unsafe|unavailable),\s*(?:pause|stop) without (?:creating|writing) the file[.!]?)?'
CREATE = r'(?:(?:please|can you|could you)\s+)?(?:create|make|build)\s+(?:a\s+)?(?:offline\s+|HTML\s+)?checklist\s+titled\s+"(?P<title>[^"\r\n]{1,120})"\s+(?:in|at|as)\s+(?P<path>[^\s"<>]{1,180}\.html)\s+with\s+(?:these\s+)?items:\s*(?P<items>"[^"\r\n]{1,160}"(?:\s*(?:,\s*(?:and\s+)?|and\s+)"[^"\r\n]{1,160}"){0,11})'

def parse_setup_request(text):
    if not isinstance(text,str) or len(text)>6000:return None
    # Every non-data clause must match. No substring creation verbs, quoted
    # instructions, user-approval conditions, future scheduling or extra actions.
    patterns = [
        r'(?:'+PREFIX+r')?(?:If|Provided that)\s+'+HEALTH+r',\s*'+CREATE+r'[.!]?'+FAILURE,
        CREATE+r'\s+only if\s+'+HEALTH+r'[.!]?'+FAILURE,
    ]
    for pattern in patterns:
        m=re.fullmatch(pattern,text.strip(),re.I)
        if m:
            return {'path':m['path'],'query':m['title'],'text':'\n'.join(re.findall(r'"([^"\r\n]+)"',m['items']))}
    return None
