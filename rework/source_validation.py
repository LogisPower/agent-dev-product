"""Bounded syntax validation. Generated source is stdin data, never executed."""
import hashlib,json,os,subprocess,sys,tempfile
from pathlib import PurePosixPath

_PARSER=r'''
import json,sys
def reject_constant(value):raise ValueError('Non-JSON numeric constant')
text=sys.stdin.buffer.read(65537)
try:
    if len(text)>65536:raise ValueError('Source exceeds syntax-check bound')
    source=text.decode('utf-8')
    if sys.argv[1]=='.py':compile(source,'<proposed>','exec',dont_inherit=True)
    else:json.loads(source,parse_constant=reject_constant)
    result={'status':'passed'}
except (SyntaxError,ValueError,RecursionError) as error:
    result={'status':'failed','error':type(error).__name__,'line':getattr(error,'lineno',None)}
print(json.dumps(result))
'''

def validate_source(path,content):
    if not isinstance(content,str) or len(content.encode())>65536:raise ValueError('Validation source bound is 64 KB')
    suffix=PurePosixPath(path).suffix.lower()
    evidence={'language':suffix or 'unknown','method':'syntax_only','sha256':hashlib.sha256(content.encode()).hexdigest(),'generated_code_executed':False,'semantic_tests_run':False}
    if suffix in ('.js','.mjs','.cjs','.ts','.mts','.cts','.jsx','.tsx'):
        from javascript_validation import validate_javascript
        return {**evidence,**validate_javascript(suffix,content)}
    if suffix not in ('.py','.json'):return {**evidence,'status':'unsupported','notice':'No trusted parser configured for this language; manual review required.'}
    try:
        result=subprocess.run([sys.executable,'-I','-S','-c',_PARSER,suffix],input=content.encode(),stdout=subprocess.PIPE,stderr=subprocess.PIPE,
            timeout=3,cwd=tempfile.gettempdir(),env={k:v for k,v in os.environ.items() if k.upper()=='SYSTEMROOT'},
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),check=False)
        if result.returncode or len(result.stdout)>2048:return {**evidence,'status':'unavailable','notice':'Trusted parser did not complete normally.'}
        return {**evidence,**json.loads(result.stdout)}
    except (OSError,subprocess.TimeoutExpired,ValueError):return {**evidence,'status':'unavailable','notice':'Trusted parser unavailable or timed out.'}
