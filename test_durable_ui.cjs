const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
class Element {
 constructor(tag,text=''){this.tag=tag;this.textContent=text;this.children=[];this.isConnected=true;this.value='';this.disabled=false;}
 append(...values){this.children.push(...values)}
 replaceChildren(...values){this.children=values}
 setAttribute(){}
}
const calls=[],notices=[];let failBuild=true;
const runs=[{id:'a'.repeat(32),kind:'local-build',status:'running',phase:'running',attempts:1}];
const context={panel:new Element('main'),crypto:require('node:crypto').webcrypto,activeView:'tasks',setInterval:()=>1,clearInterval:()=>{},
 el:(tag,cls,text)=>new Element(tag,text),card:(title,detail,meta)=>new Element('article',title+' '+meta),
 action:(label,fn)=>Object.assign(new Element('button',label),{onclick:fn}),notify:t=>notices.push(t),
 api:async(path,body,headers)=>{
   calls.push({path,body,headers});
   if(path.endsWith('/dispatch'))return {worker:'running',runs};
   if(path.endsWith('/builds')){if(failBuild){failBuild=false;throw Error('Synthetic uncertain network result')}return {status:'running'};}
   if(path.endsWith('/cancel')){runs[0].cancel_requested=true;return {status:'running'}}
   throw Error('Unexpected path '+path);
 }};
vm.createContext(context);vm.runInContext(fs.readFileSync(__dirname+'/durable-runs.js','utf8'),context);
function all(node){return [node,...node.children.flatMap(all)]}
(async()=>{
 await vm.runInContext('mountDurableRuns(panel,"project-one")',context);
 let nodes=all(context.panel);
 const textarea=nodes.find(n=>n.tag==='textarea'),button=nodes.find(n=>n.textContent==='Queue offline build');
 textarea.value='Keep the original design';await button.onclick();
 assert.equal(textarea.value,'Keep the original design');assert.equal(button.disabled,false);
 await button.onclick();
 const builds=calls.filter(c=>c.path.endsWith('/builds'));
 assert.equal(builds.length,2);assert.equal(builds[0].headers['Idempotency-Key'],builds[1].headers['Idempotency-Key']);
 assert.equal(textarea.value,'');
 nodes=all(context.panel);await nodes.find(n=>n.textContent==='Cancel').onclick();
 assert(calls.some(c=>c.path.endsWith('/builds/'+ 'a'.repeat(32)+'/cancel')));
 assert(all(context.panel).some(n=>n.textContent==='Cancellation requested'));
 console.log('PASS: original-style component rendering, uncertain-submit idempotency, draft preservation, scoped cancel and status refresh. DOM fixture; not browser visual acceptance.');
})().catch(error=>{console.error(error);process.exitCode=1});
