"""Pure public-query relevance rules. No requests, credentials or model calls."""
import re
STOP=set('find locate explaining citing page docs documentation use when one the and for are what how can could would you that this with from about search web please public read summarize explain provides provide official documentation information tell me latest current does do is a an it its'.split())
def terms(text):
    return {x.casefold()[:-1] if x.casefold().endswith('s') and len(x)>4 else x.casefold() for x in re.findall(r'[A-Za-z][A-Za-z0-9_-]{1,}',text) if x.casefold() not in STOP}
def search_excerpt(query):
    # Only remove an explicit trailing response instruction. Never add private
    # context, inferred entities or guessed search terms.
    value=re.split(r'(?i)\s+and\s+(?:explain|summarize|tell me|describe)\b',query,maxsplit=1)[0].strip()
    value=re.sub(r'(?i)^(?:please\s+)?(?:find|locate|search(?: the web| online)? for|look up)\s+(?:the\s+)?','',value)
    value=re.sub(r'(?i)\b(?:explaining|describing)\b','',value)
    return re.sub(r'\s+',' ',value).strip(' .?!') or query
def score(query,title,text):
    wanted=terms(search_excerpt(query));seen=terms(text);headline=terms(title)
    if not wanted:return 0
    overlap=wanted & (seen|headline)
    # Every requested topical token must appear; a generic homepage matching
    # only a broad ecosystem term is insufficient. This is not entailment proof.
    if overlap!=wanted:return 0
    return len(overlap)+2*len(wanted&headline)
def ranked(query,results):
    rows=[]
    for index,item in enumerate(results[:10]):
        value=score(query,item.get('title',''),item.get('snippet','')+' '+item.get('url',''))
        if value>0:rows.append((value,-index,item))
    return [x[2] for x in sorted(rows,key=lambda x:(x[0],x[1]),reverse=True)]
def excerpt(query,text,limit=4000):
    # Retain context around the first topical hit rather than only site menus.
    wanted=terms(search_excerpt(query));matches=[m.start() for m in re.finditer(r'\b[\w-]+\b',text) if m.group().casefold() in wanted]
    start=max(0,(matches[0] if matches else 0)-600)
    return text[start:start+limit]
