"""Conservative complete-request grammar for current host-clock reads.

This optimization never consumes a clause of a mixed request. Unknown forms
remain with the general planner; timezone abbreviations are not guessed.
"""
import re

def clock_request(text):
    if not isinstance(text,str) or len(text)>300:return None
    t=text.strip().replace('\u2019',"'")
    t=re.sub(r'[?.!]$', '', t).strip()
    t=re.sub(r'(?i)^please\s+', '', t)
    t=re.sub(r'(?i)^(?:can|could|would) you\s+', '', t)
    t=re.sub(r'(?i)^please\s+', '', t)
    # Restrict the entire request, including zone, before dispatch. No quoted
    # instructions, extra verbs, URLs or trailing commands can enter this path.
    unit=r'(?:date|time|day)(?:\s+and\s+(?:date|time|day))?'
    question=rf"(?:what(?:'s| is)\s+(?:the\s+)?(?:current\s+)?{unit}|what\s+{unit}\s+is it|(?:tell me|show me|give me)\s+(?:the\s+)?(?:current\s+)?{unit}|(?:current\s+){unit})"
    m=re.fullmatch(rf"(?i){question}(?:\s+(?:today|now))?(?:\s+(?:in\s+)?(?P<zone>UTC|GMT|Z|[A-Za-z]+(?:/[A-Za-z0-9_+\-]+)+|EST|EDT|CST|CDT|MST|MDT|PST|PDT))?(?:\s+(?:today|now))?",t)
    if not m:return None
    zone=m.group('zone')
    if zone and zone.upper() in {'EST','EDT','CST','CDT','MST','MDT','PST','PDT'}:
        return {'clarification':'Please specify an IANA timezone such as America/New_York or UTC; I will not guess from an abbreviation.'}
    if zone and zone.upper() in {'UTC','GMT','Z'}:zone='UTC'
    return {'timezone':zone}
