"""Conservative per-turn routing. Tool/build work stays on the larger model."""
import re

LARGE='bonsai2-27b'
FAST='bonsai2-9b-vision'

def choose(requested,instruction,mode,history,attachments):
    if requested in (LARGE,FAST):return requested,'Selected manually'
    text=instruction.strip()
    if mode=='build':return LARGE,'Build work uses the stronger model'
    if attachments:return LARGE,'Document and image tasks retain the stronger orchestrator; vision uses 9B as a tool'
    if sum(len(x.get('content','')) for x in history[-16:])>7000:return LARGE,'Conversation needs the larger context window'
    if len(text)>350:return LARGE,'Detailed request uses the stronger model'
    if re.search(r'\b(file|files|folder|desktop|search|browse|internet|web|tool|command|cli|terminal|install|deploy|code|debug|python|javascript|app|website|build|plan|design|architecture|analy[sz]e|compare|decid[ei]|medical|health|legal|financial|rag|memory|task|project|continue|explain|why|math|calculate)\b',text,re.I):
        return LARGE,'Reasoning or tool use retains the stronger model'
    if re.fullmatch(r'(hi|hello|hey|thanks|thank you|good (morning|evening|night)|how are you)[!?. ]*',text,re.I):
        return FAST,'Simple conversation uses the faster model'
    if re.match(r'^(rewrite|rephrase|fix spelling|correct spelling|make this (shorter|polite))\b',text,re.I):
        return FAST,'Short text editing uses the faster model'
    return LARGE,'Uncertain complexity defaults to the stronger model'
