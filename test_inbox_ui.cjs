const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
class Element{
 constructor(tag,text=''){this.tag=tag;this.textContent=text;this.children=[];this.isConnected=true;this.value='';this.disabled=false;}
 append(...items){this.children.push(...items)}
 replaceChildren(...items){this.children=items}
 setAttribute(){}
 add(item){this.append(item)}
}
const host=new Element('main'),calls=[],selected=[],notices=[];let page=0,resolveLate,rejectSelection=true;
const task=(id,status,dependencies=[])=>({id,status,kind:'file_write',payload:{path:id+'.txt'},dependencies});
const pages=[
 {tasks:[task('approval','approval'),task('interrupted','needs_review'),task('done','completed')],next_cursor:4,has_more:true},
 {tasks:[task('approval','completed'),task('blocked','waiting',[{task:'creator',path:'source.txt',status:'completed',sha256:null}]),task('ready','waiting',[{task:'creator2',path:'ready.txt',status:'completed',sha256:'abc'}])],next_cursor:8,has_more:false},
 {tasks:[task('blocked','completed'),task('interrupted','completed')],next_cursor:10,has_more:false}
];
const context={current:'p1',activeView:'inbox',DESCRIPTIONS:{inbox:['Inbox']},loadView:async()=>{},
 document:{addEventListener:(_name,fn)=>fn()},Option:class extends Element{constructor(name,id){super('option',name);this.value=id}},
 $:()=>host,el:(tag,cls,text)=>new Element(tag,text),card:(title,detail,meta)=>new Element('article',title+' '+meta),
 action:(label,fn)=>Object.assign(new Element('button',label),{onclick:fn}),notify:message=>notices.push(message),
 select:async id=>{if(rejectSelection)throw Error('Project access changed');selected.push(id)},setView:view=>{context.activeView=view},
 api:async(path,body)=>{
  assert.equal(body,undefined,'Inbox must not issue a mutation');calls.push(path);
  if(path==='/api/projects')return [{id:'p1',name:'One'},{id:'p2',name:'Two'}];
  if(path==='/api/projects/p2/foundation?after=0')return new Promise(resolve=>{resolveLate=resolve});
  assert.equal(path,'/api/projects/p1/foundation?after='+[0,4,8][page]);
  return {...pages[page++],worker:'idle'};
 }};
vm.createContext(context);vm.runInContext(fs.readFileSync(__dirname+'/canonical-views.js','utf8'),context);
const all=node=>[node,...node.children.flatMap(all)],buttons=()=>all(host).filter(x=>x.tag==='button');
(async()=>{
 await context.loadView('inbox');
 assert.equal(all(host).filter(x=>x.tag==='article').length,2);
 assert(all(host).some(x=>x.textContent.includes('More saved events remain')));
 await buttons().find(x=>x.textContent==='Load more saved events').onclick();
 const cards=all(host).filter(x=>x.tag==='article');assert.equal(cards.length,2);
 assert(cards.some(x=>x.textContent.startsWith('blocked.txt')));
 assert(!cards.some(x=>x.textContent.startsWith('ready.txt')||x.textContent.startsWith('approval.txt')));
 await buttons().find(x=>x.textContent==='Review in Tasks').onclick();
 assert.deepEqual(notices,['Project access changed']);assert.deepEqual(selected,[]);assert.equal(context.activeView,'inbox');
 rejectSelection=false;
 await buttons().find(x=>x.textContent==='Review in Tasks').onclick();assert.deepEqual(selected,['p1']);assert.equal(context.activeView,'tasks');
 context.activeView='inbox';await buttons().find(x=>x.textContent==='Refresh inbox').onclick();
 assert.equal(all(host).filter(x=>x.tag==='article').length,0);
 context.current='p2';const pending=context.loadView('inbox');await new Promise(resolve=>setImmediate(resolve));
 context.activeView='files';await context.loadView('files');
 resolveLate({tasks:[task('stale','approval')],next_cursor:1,has_more:false,worker:'idle'});await pending;
 assert(!all(host).some(x=>x.textContent.startsWith('stale.txt')));
 assert.equal(calls.filter(x=>x.includes('/p2/foundation')).length,1);
 console.log('PASS: scoped Inbox paging, committed-artifact readiness, completed-item removal, rejected project selection, Tasks navigation, read-only requests and stale-response suppression. DOM fixture, not browser acceptance.');
})().catch(error=>{console.error(error);process.exitCode=1});
