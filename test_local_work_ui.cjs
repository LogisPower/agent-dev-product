const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
class Element{
 constructor(tag,text=''){this.tag=tag;this.textContent=text;this.children=[];this.isConnected=true;this.value='';this.disabled=false;}
 append(...items){this.children.push(...items)}replaceChildren(...items){this.children=items}setAttribute(n,v){this[n]=v}
}
const panel=new Element('main'),calls=[],timers=[];let failed=false,approved=false,planFailed=false,proposalFailed=false;
const task={id:'b'.repeat(32),version:1,status:'approval',targets:[{path:'a.txt',old:'before',new:'after',expected_sha256:'a'.repeat(64)}],dependencies:[]};
const context={window:{},crypto:require('node:crypto').webcrypto,
 el:(tag,cls,text)=>new Element(tag,text),card:(title,sub,status)=>new Element('article',title+' '+status),
 action:(text,fn)=>Object.assign(new Element('button',text),{onclick:fn}),
 setInterval:fn=>{timers.push(fn);return timers.length},clearInterval:()=>{},
 api:async(path,body)=>{
   if(body){calls.push({path,body});assert.equal(body.project,'p');
     if(body.action==='submit'){if(!failed){failed=true;throw Error('Uncertain reply')}return task}
     if(body.action==='plan'){
       if(!planFailed){planFailed=true;throw Error('Uncertain plan reply')}
       return {id:'plan-one',tasks:body.steps.map((step,index)=>({...task,id:(index?'e':'d').repeat(32),targets:[step.edit],plan:{id:'plan-one',title:body.title,position:index+1,total:body.steps.length,after:step.after}}))};
     }
     if(body.action==='propose'){
       assert.equal(path,'/api/local-planning');if(!proposalFailed){proposalFailed=true;throw Error('Uncertain proposal reply')}
       return {id:'f'.repeat(32),kind:'local_plan',version:1,status:'completed',targets:[],planning:{goal:body.goal,paths:body.paths},result:{proposal:{title:'Proposed',steps:[]},executed:false}};
     }
     if(body.action==='verify'){if(!context.verificationFailed){context.verificationFailed=true;throw Error('Uncertain verification reply')}return {id:'5'.repeat(32),kind:'local_verify',version:1,status:'queued',targets:[],verification:{paths:body.paths}}};
     if(body.action==='analyze'){if(!context.analysisFailed){context.analysisFailed=true;throw Error('Uncertain analysis reply')}return {id:'6'.repeat(32),kind:'local_analysis',version:3,status:'completed',targets:[],result:{read_only:true}}};
     if(body.action==='from-analysis')return {id:'7'.repeat(32),kind:'local_plan',version:1,status:'queued',targets:[]};
     if(body.action==='mixed')return {id:'mixed-id',tasks:[{id:'writer',status:'approval'}],steps:[{validation:{status:'passed',semantic_tests_run:false}}]};
     if(body.action==='author'){if(!context.authorFailed){context.authorFailed=true;throw Error('Uncertain author reply')}return {id:'4'.repeat(32),kind:'local_author',version:3,status:'completed',targets:[],result:{proposal:{path:'new.py',content:'VALUE = 1'}}}};
     if(body.action==='accept-author')return {write:{id:'writer',status:'approval'},verify:{id:'verification',status:'queued'}};
     if(body.action==='author-workflow')return {read_only:true,tasks:[{id:'writer',status:'approval'}]};
     if(body.action==='discover')return {id:'2'.repeat(32),kind:'local_discovery',version:3,status:'completed',targets:[],result:{notice:'Bounded discovery',truncated:true,candidates:[{path:'a.txt',blocked_by:[],completed_unchanged:'previous'}]}};
     if(body.action==='from-discovery')return {id:'3'.repeat(32),kind:'local_plan',status:'queued',version:1,targets:[]};
     if(body.action==='accept'){assert.equal(path,'/api/local-planning');return {id:'accepted-proposal',tasks:[{...task,id:'1'.repeat(32)}]}}
     assert.equal(body.action,'approve');approved=true;return {...task,status:'waiting'};
   }
   if(path==='/api/projects/p/local-planning/mixed')return {read_only:true,plans:[{id:'mixed-id'}]};
   const url=new URL(path,'http://synthetic');assert.equal(url.searchParams.get('project'),'p');
   if(url.searchParams.get('action')==='prepare'){const selected=url.searchParams.get('path');return {status:'ok',path:selected,content:selected==='b.txt'?'second':'before',sha256:(selected==='b.txt'?'b':'a').repeat(64),next_offset:null}}
   if(url.searchParams.get('action')==='context')return {read_only:true,tasks:[{id:task.id,guidance:'completed_do_not_reexecute'}],files:{}};
   if(url.searchParams.get('action')==='workflow')return {read_only:true,phase:'execution_review',automatic_retry:false};
   return {tasks:failed?[{...task,status:approved?'waiting':'approval'}]:[],next_cursor:0,has_more:false,worker:'stopped',planning_enabled:true};
 }
};
vm.createContext(context);vm.runInContext(fs.readFileSync(__dirname+'/local-work.js','utf8'),context);
const all=n=>[n,...n.children.flatMap(all)],button=label=>all(panel).find(n=>n.tag==='button'&&n.textContent===label),input=label=>all(panel).find(n=>n['aria-label']===label);
(async()=>{
 context.window.mountLogisLocalWork(panel,'p');await new Promise(r=>setImmediate(r));
 input('Local edit file').value='a.txt';await button('Load current file').onclick();
 input('Exact original text').value='before';input('Replacement text').value='after';
 await button('Submit for local approval').onclick();
 assert.equal(input('Replacement text').value,'after');assert.equal(button('Submit for local approval').disabled,false);
 await button('Submit for local approval').onclick();assert.equal(calls.length,2);
 assert.equal(calls[0].body.key,calls[1].body.key);assert.equal(calls[1].body.edits[0].expected_sha256,'a'.repeat(64));
 assert.equal(approved,false);assert(all(panel).some(n=>n.textContent.includes('Approved jobs wait')));
 const detail=all(panel).find(n=>n.tag==='article').children.find(n=>n.tag==='details');detail.open=true;
 await button('Refresh local tasks').onclick();assert(all(panel).includes(detail));assert.equal(detail.open,true);
 await button('Approve local edit').onclick();assert.equal(approved,true);
 assert.equal(calls[2].body.task,task.id);assert.equal(calls[2].body.version,1);
 input('Replacement text').value='different';await button('Submit for local approval').onclick();assert.notEqual(calls[3].body.key,calls[0].body.key);
 input('Predecessor task ID').value='c'.repeat(32);await button('Submit for local approval').onclick();assert.equal(calls.length,4);
 input('Predecessor task ID').value='';await button('Add edit to plan').onclick();
 input('Local edit file').value='b.txt';await button('Load current file').onclick();input('Exact original text').value='second';input('Replacement text').value='done';await button('Add edit to plan').onclick();
 input('Local plan title').value='Two file plan';await button('Submit plan for review').onclick();await button('Submit plan for review').onclick();
 const plans=calls.filter(c=>c.body.action==='plan');assert.equal(plans.length,2);assert.equal(plans[0].body.key,plans[1].body.key);
 assert.equal(plans[1].body.steps.length,2);assert.equal(plans[1].body.steps[1].after[0],'step-1');assert.equal(input('Replacement text').value,'done');
 assert.equal(calls.filter(c=>c.body.action==='approve').length,1);await button('Remove step 2').onclick();await button('Submit plan for review').onclick();
 const changed=calls.filter(c=>c.body.action==='plan').at(-1);assert.equal(changed.body.steps.length,1);assert.notEqual(changed.body.key,plans[0].body.key);
 const count=calls.length;await button('Check existing work before planning').onclick();assert.equal(calls.length,count);assert(all(panel).some(n=>n.textContent.includes('completed_do_not_reexecute')));
 input('Local planning goal').value='Make a small change';input('Files for local planning').value='a.txt';
 await button('Ask local model for a plan').onclick();assert.equal(input('Local planning goal').value,'Make a small change');
 await button('Ask local model for a plan').onclick();const proposals=calls.filter(c=>c.body.action==='propose');assert.equal(proposals.length,2);assert.equal(proposals[0].body.key,proposals[1].body.key);
 assert.equal(calls.filter(c=>c.body.action==='accept').length,0);await button('Create review tasks from proposal').onclick();
 assert.equal(calls.filter(c=>c.body.action==='accept').length,1);assert.equal(calls.filter(c=>c.body.action==='approve').length,1);
 const beforeInspect=calls.length;await button('Inspect proposal workflow').onclick();assert.equal(calls.length,beforeInspect);assert(all(panel).some(n=>n.textContent.includes('execution_review')));
 input('Discovery query').value='before';await button('Discover project files').onclick();await button('Discover project files').onclick();
 const discoveries=calls.filter(c=>c.body.action==='discover');assert.equal(discoveries.length,2);assert.equal(discoveries[0].body.key,discoveries[1].body.key);
 input('Files for local planning').value='';await button('Select a.txt').onclick();assert.equal(input('Files for local planning').value,'a.txt');
 await button('Plan selected discoveries').onclick();assert.equal(calls.at(-1).body.allow_completed,false);
 input('New goal for completed files').checked=true;await button('Plan selected discoveries').onclick();assert.equal(calls.at(-1).body.allow_completed,true);
 assert.equal(calls.filter(c=>c.body.action==='approve').length,1);assert(all(panel).some(n=>n.textContent.includes('Search was truncated')));
 input('New file path').value='new.py';await button('Draft a new file locally').onclick();await button('Draft a new file locally').onclick();
 const authors=calls.filter(c=>c.body.action==='author');assert.equal(authors.length,2);assert.equal(authors[0].body.key,authors[1].body.key);assert.equal(input('New file path').value,'new.py');
 assert.equal(calls.filter(c=>c.body.action==='accept-author').length,0);await button('Save new file for review').onclick();assert.equal(calls.filter(c=>c.body.action==='approve').length,1);
 await button('Inspect new-file workflow').onclick();assert.equal(calls.at(-1).body.action,'author-workflow');assert(all(panel).some(n=>n.textContent.includes('Background work')));
 await button('Add proposal to mixed plan').onclick();input('Mixed plan title').value='Mixed files';await button('Validate and save mixed plan').onclick();await button('Validate and save mixed plan').onclick();
 const mixed=calls.filter(c=>c.body.action==='mixed');assert.equal(mixed.length,2);assert.equal(mixed[0].body.key,mixed[1].body.key);assert.equal(mixed[0].body.allow_unsupported,false);
 input('Manual review for unsupported languages').checked=true;await button('Validate and save mixed plan').onclick();assert.equal(calls.at(-1).body.allow_unsupported,true);assert.equal(calls.filter(c=>c.body.action==='approve').length,1);
 await button('Inspect saved mixed plans').onclick();assert(all(panel).some(n=>n.textContent.includes('mixed-id')));await button('Remove proposal 1').onclick();
 input('Files for project verification').value='a.js\nb.ts';await button('Start current-file verification').onclick();await button('Start current-file verification').onclick();
 const checks=calls.filter(c=>c.body.action==='verify');assert.equal(checks.length,2);assert.equal(checks[0].body.key,checks[1].body.key);assert.equal(input('Files for project verification').value,'a.js\nb.ts');
 await button('Start current-file verification').onclick();assert.notEqual(calls.at(-1).body.key,checks[1].body.key);assert.equal(calls.filter(c=>c.body.action==='approve').length,1);
 input('Source for read-only analysis').value='large.txt';await button('Analyze larger source locally').onclick();await button('Analyze larger source locally').onclick();
 const analyses=calls.filter(c=>c.body.action==='analyze');assert.equal(analyses.length,2);assert.equal(analyses[0].body.key,analyses[1].body.key);assert.equal(input('Source for read-only analysis').value,'large.txt');
 await button('Start a fresh analysis').onclick();const fresh=calls.filter(c=>c.body.action==='analyze').at(-1);assert.notEqual(fresh.body.key,analyses[1].body.key);assert.equal(input('Source for read-only analysis').value,'large.txt');
 await button('Plan selected files with this analysis').onclick();assert.equal(calls.at(-1).body.action,'from-analysis');assert.equal(calls.filter(c=>c.body.action==='approve').length,1);
 console.log('PASS: local tasks, analysis/planning, preserved drafts/keys, dependencies and separate approvals. DOM fixture, not visual browser acceptance.');
})().catch(e=>{console.error(e);process.exitCode=1});
