"""Fixed built-in Node parser; never resolve or execute project modules."""
import json,os,subprocess,sys,tempfile
from pathlib import Path

NODE=Path(sys.executable).parent.parent/'node'/'bin'/'node.exe'
SCRIPT=r'''
const fs=require('node:fs'),vm=require('node:vm'),mod=require('node:module');
const suffix=process.argv[1];let source=fs.readFileSync(0,'utf8');
let result;
try {
  if(Buffer.byteLength(source)>65536)throw Error('Input bound exceeded');
  if(['.ts','.mts','.cts'].includes(suffix)){
    if(typeof mod.stripTypeScriptTypes!=='function'){console.log(JSON.stringify({status:'unavailable',notice:'Built-in TypeScript parser unavailable'}));process.exit(0)}
    source=mod.stripTypeScriptTypes(source,{mode:'transform'});
  }
  if(['.cjs','.cts'].includes(suffix))vm.compileFunction(source,['exports','require','module','__filename','__dirname']);
  else new vm.SourceTextModule(source);
  result={status:'passed'};
} catch(error){result={status:'failed',error:typeof error.name==='string'?error.name:'ParseError',code:typeof error.code==='string'?error.code:null};}
console.log(JSON.stringify(result));
'''

def validate_javascript(suffix,content):
    mode='commonjs' if suffix in ('.cjs','.cts') else 'module'
    evidence={'parser':'node_builtin','module_mode':mode,'type_checking':False,'imports_resolved':False}
    if suffix in ('.jsx','.tsx'):return {**evidence,'status':'unsupported','notice':'JSX/TSX requires a separately configured trusted parser.'}
    if not NODE.is_file():return {**evidence,'status':'unavailable','notice':'Trusted bundled Node runtime unavailable.'}
    try:
        result=subprocess.run([str(NODE),'--no-warnings','--experimental-vm-modules','-e',SCRIPT,suffix],input=content.encode(),
            stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=3,cwd=tempfile.gettempdir(),
            env={k:v for k,v in os.environ.items() if k.upper()=='SYSTEMROOT'},creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),check=False)
        if result.returncode or len(result.stdout)>2048:return {**evidence,'status':'unavailable','notice':'Trusted Node parser did not complete normally.'}
        return {**evidence,**json.loads(result.stdout)}
    except (OSError,subprocess.TimeoutExpired,ValueError):return {**evidence,'status':'unavailable','notice':'Trusted Node parser unavailable or timed out.'}
