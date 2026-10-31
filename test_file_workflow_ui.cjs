const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
class Element{
 constructor(tag,text=''){this.tag=tag;this.textContent=text;this.children=[];this.isConnected=true;this.value='';this.disabled=false;this.readOnly=false;}
 append(...items){this.children.push(...items)}
 replaceChildren(...items){this.children=items}
 setAttribute(name,value){this[name]=value}
}
const panel=new Element('main'),calls=[];let fail=true;
const context={window:{},esc:encodeURIComponent,URLSearchParams,crypto:require('node:crypto').webcrypto,
 el:(tag,cls,text)=>new Element(tag,text),action:(text,fn)=>Object.assign(new Element('button',text),{onclick:fn}),
 request:async path=>{
  const url=new URL(path,'http://synthetic');assert.equal(url.pathname,'/api/projects/project-one/foundation');
  if(url.searchParams.get('action')==='list')return {entries:[{path:'a.txt',kind:'file'}],next_cursor:null};
  assert.equal(url.searchParams.get('action'),'read');assert.equal(url.searchParams.get('path'),'a.txt');
  return {status:'ok',content:'before',characters:6,next_offset:null,sha256:'a'.repeat(64)};
 },
 mutation:async(path,body)=>{calls.push({path,body});assert.equal(path,'/api/projects/project-one/foundation/write_verify');if(fail){fail=false;throw Error('Uncertain synthetic response')}return {write:{id:'writer'},verify:{id:'reader'}}}
};
const source=fs.readFileSync(__dirname+'/canonical-ui.js','utf8');
const start=source.indexOf(' window.mountLogisProjectFiles='),end=source.indexOf(" document.addEventListener('DOMContentLoaded'",start);
assert(start>=0&&end>start);vm.createContext(context);vm.runInContext(source.slice(start,end),context);
const all=node=>[node,...node.children.flatMap(all)],button=label=>all(panel).find(x=>x.tag==='button'&&x.textContent===label);
(async()=>{
 context.window.mountLogisProjectFiles(panel,'project-one');await new Promise(resolve=>setImmediate(resolve));
 button('a.txt').onclick();await new Promise(resolve=>setImmediate(resolve));
 const editor=all(panel).find(x=>x.tag==='textarea');editor.value='reviewed draft';
 const save=button('Propose reviewed file change');await save.onclick();
 assert.equal(editor.value,'reviewed draft');assert.equal(editor.readOnly,false);assert.equal(save.disabled,false);
 await save.onclick();assert.equal(calls.length,2);assert.equal(calls[0].body.key,calls[1].body.key);
 assert.equal(calls[1].body.kind,'file_write');assert.equal(calls[1].body.payload.expected_sha256,'a'.repeat(64));
 assert.equal(calls[1].body.payload.content,'reviewed draft');assert.equal(editor.readOnly,true);
 assert(all(panel).some(x=>x.textContent.includes('approve writer')&&x.textContent.includes('Verification reader')));
 console.log('PASS: original file editor submits one durable write/verify workflow, preserves draft and key after uncertain response, displays both jobs and performs no approval. DOM fixture, not browser acceptance.');
})().catch(error=>{console.error(error);process.exitCode=1});
