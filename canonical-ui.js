/* Optional adapter for the original Logis UI. Credentials live only in memory. */
(() => {
 'use strict';
 let credential='', csrf='', resolveAuth;
 const projectVersions=new Map();
 const authenticated=new Promise(resolve=>{resolveAuth=resolve}), pendingKeys=new Map();
 const esc=encodeURIComponent;
 async function request(path,body,headers={},method=body===undefined?'GET':'POST',wait=true){
  if(wait)await authenticated;
  const response=await fetch(path,{method,credentials:'same-origin',headers:{'Content-Type':'application/json',...(credential?{Authorization:'Bearer '+credential}:{}),...(csrf?{'X-Logis-CSRF':csrf}:{}),...headers},...(body===undefined?{}:{body:JSON.stringify(body)})});
  let data;try{data=await response.json()}catch{throw Error('The canonical workspace did not return JSON.')}
  if(!response.ok)throw Error(typeof data.detail==='string'?data.detail:JSON.stringify(data.detail||data.error||'Request failed'));
  return data;
 }
 async function mutation(path,body,headers={},method='POST'){
  const fingerprint=JSON.stringify([path,body,method]);
  if(!pendingKeys.has(fingerprint))pendingKeys.set(fingerprint,crypto.randomUUID());
  const result=await request(path,body,{'Idempotency-Key':pendingKeys.get(fingerprint),...headers},method);
  pendingKeys.delete(fingerprint);return result;
 }
 function unsupported(){throw Error('This action is not connected to the canonical workspace yet. No change was made.')}
 window.logisCanonicalRequest=async(path,body,headers={})=>{
  const url=new URL(path,location.origin), p=url.pathname;
  if(p==='/api/local-work'){
   if(body){const {project,action,...args}=body;return mutation('/api/projects/'+esc(project)+'/local-work/'+esc(action),args,headers)}
   const project=url.searchParams.get('project');url.searchParams.delete('project');
   return request('/api/projects/'+esc(project)+'/local-work?'+url.searchParams.toString());
  }
  if(p==='/api/local-planning'&&body){const {project,action,...args}=body;return mutation('/api/projects/'+esc(project)+'/local-planning/'+esc(action),args,headers)}
  if(p==='/api/foundation'){
   if(body){const {project,action,...args}=body;return mutation('/api/projects/'+esc(project)+'/foundation/'+esc(action),args,headers)}
   const project=url.searchParams.get('project');url.searchParams.delete('project');
   return request('/api/projects/'+esc(project)+'/foundation?'+url.searchParams.toString());
  }
  if(p==='/api/projects'){const rows=await request(path);for(const row of rows)projectVersions.set(row.id,row.version);return rows.filter(x=>!x.trashed&&!!x.archived===(url.searchParams.get('archived')==='1'))}
  if(p==='/api/export')return request('/api/projects/'+esc(url.searchParams.get('id'))+'/export');
  if(p==='/api/state'){
   const id=url.searchParams.get('id');
   const [s,d,meta]=await Promise.all([request(path),request('/api/projects/'+esc(id)+'/dispatch'),request('/api/projects/'+esc(id)+'/settings')]);projectVersions.set(id,meta.version);
   const r=d.runs.find(x=>x.kind==='local-chat'&&x.status==='running');
   return {...s,...meta,files:[],attachments:[],job:r?{id:r.id,status:'running',phase:r.cancel_requested?'stopping':r.phase,events:[{text:r.phase==='queued'?'Queued: waiting for the shared model slot.':r.notice||'Reply is running.'}],started:new Date().toISOString()}:null};
  }
  if(p==='/api/update'||p==='/api/trash'||p==='/api/restore-trash'){
   if(body===undefined&&p==='/api/trash'){const rows=await request('/api/projects');for(const row of rows)projectVersions.set(row.id,row.version);return rows.filter(x=>x.trashed)}
   const {id,expected_version,...values}=body;
   const version=expected_version??projectVersions.get(id);if(!version)throw Error('Reload this project before changing its metadata.');
   const changes=p==='/api/trash'?{trash:true}:p==='/api/restore-trash'?{trash:false}:values;
   const result=await mutation('/api/projects/'+esc(id)+'/settings',{...changes,expected_version:version},headers,'PATCH');projectVersions.set(id,result.version);return result;
  }
  if(p==='/api/run'){
   if(body.action!=='chat'||body.edit_index!==undefined||body.task_id||body.attachments?.length)unsupported();
   return body.mode==='build'?mutation('/api/projects/'+esc(body.id)+'/builds',{prompt:body.message},headers):mutation('/api/projects/'+esc(body.id)+'/chat',{content:body.message},headers);
  }
  if(p==='/api/stop'){
   const d=await request('/api/projects/'+esc(body.id)+'/dispatch'),r=d.runs.find(x=>x.kind==='local-chat'&&x.status==='running');
   if(!r)throw Error('No active chat run. Refresh the run list.');
   return request('/api/projects/'+esc(body.id)+'/chat/runs/'+esc(r.id)+'/cancel',{});
  }
  if(p==='/api/workspace-item'){
   if(!['tasks','decisions','cases','conference','routines','pipelines','skills','agents','org'].includes(body.kind))unsupported();
   const project=body.project_id||current;
   if(!project)throw Error('Open the project that should own this record first.');
   if(body.id){
    const version=body.expected_version??body.version;
    if(!Number.isInteger(version))throw Error('Reopen this record before saving; its version is required.');
    return mutation('/api/projects/'+esc(project)+'/objects/'+esc(body.id),{expected_version:version,title:body.title,detail:body.detail||'',status:body.status},headers,'PATCH');
   }
   return mutation('/api/projects/'+esc(project)+'/objects',{kind:body.kind,title:body.title,detail:body.detail||'',status:body.status},headers);
  }
  if(p==='/api/workspace'){
   const view=url.searchParams.get('view');
   if(view==='projects')return (await request('/api/projects')).filter(x=>!x.archived&&!x.trashed);
   if(view==='dashboard'){
    const [projects,tasks]=await Promise.all([request('/api/projects'),request('/api/workspace?view=tasks')]);
    // Limit fan-out; never imply this is an unbounded workspace-wide run inventory.
    const selected=projects.filter(x=>!x.archived).slice(0,20);
    const dispatch=await Promise.all(selected.map(x=>request('/api/projects/'+esc(x.id)+'/dispatch')));
    return {projects:projects.length,tasks,open_tasks:tasks.filter(x=>!['done','archived'].includes(x.status)).length,active_jobs:dispatch.flatMap(x=>x.runs.filter(r=>r.status==='running')),recent_projects:selected,stack:{storage:'Canonical PostgreSQL',queue:'Durable dispatch; one model slot'},paperclip:{online:false,reason:'Not connected through this interface.'}};
   }
   if(['tasks','decisions','cases','routines','pipelines','org','conference'].includes(view))return request(path);
   if(view==='skills')return {records:await request(path),tools:[]};
   unsupported();
  }
  if(p==='/api/events'||p.startsWith('/api/objects/')||p.startsWith('/api/projects/')||p.startsWith('/api/foundation/'))return body===undefined?request(path):mutation(path,body,headers);
  unsupported();
 };
 window.mountLogisProjectFiles=(panel,project)=>{
  const section=el('section','view-body canonical-files'),directory=el('input'),query=el('input'),status=el('p','muted'),entries=el('div','card-grid'),reader=el('section'),base='/api/projects/'+esc(project)+'/foundation';
  directory.setAttribute('aria-label','Project directory');directory.placeholder='Project directory (empty means root)';query.setAttribute('aria-label','Find file name');query.placeholder='Literal filename search';
  let epoch=0,pageCursor=null,lastQuery=null;
  const read=async(path,offset=0,sha=null,create=false)=>{
   const generation=++epoch;reader.replaceChildren();
   try{
    let data=await request(base+'?'+new URLSearchParams({action:'read',path,offset,...(sha?{sha256:sha}:{})}));
    if(generation!==epoch||!section.isConnected)return;
    if(data.status==='missing'){
     if(!create){status.textContent=data.next_action;return}
     data={content:'',characters:0,next_offset:null,sha256:undefined};
    }else if(create){status.textContent='That file already exists. Open its current version before editing.';return}
    status.textContent='Current version loaded. A proposed change must still be approved before writing.';
    const editor=el('textarea'),info=el('p','muted');editor.value=data.content;editor.setAttribute('aria-label','Current file content');editor.rows=10;
    const complete=offset===0&&data.next_offset===null;editor.readOnly=!complete;
    info.textContent=path+' | '+(data.sha256?'SHA-256 '+data.sha256:'New file; absent at last check')+' | Characters '+offset+'–'+(offset+data.content.length)+' of '+data.characters;
    reader.append(info,editor);
    if(data.next_offset!==null)reader.append(action('Read next page',()=>read(path,data.next_offset,data.sha256)));
    if(complete){
     let proposal=null;
     const save=action('Propose reviewed file change',async()=>{
      const content=editor.value;if(!proposal||proposal.content!==content)proposal={key:crypto.randomUUID(),content};save.disabled=true;
      try{const flow=await mutation(base+'/write_verify',{key:proposal.key,kind:'file_write',payload:{path,content,expected_sha256:data.sha256}});status.textContent='Change proposed. Review and approve '+flow.write.id+' in Background work. Verification '+flow.verify.id+' will wait for its committed file.';proposal=null;editor.readOnly=true}
      catch(error){status.textContent=error.message;save.disabled=false}
     });reader.append(save);
    }else reader.append(el('p','muted','Paged reads are read-only to prevent replacing a whole file with one page.'));
   }catch(error){if(generation===epoch)status.textContent=error.message}
  };
  const list=async(more=false)=>{
   const generation=++epoch;reader.replaceChildren();
   if(!more){pageCursor=null;lastQuery={directory:directory.value,query:query.value};entries.replaceChildren()}
   const args={action:lastQuery.query?'search':'list',directory:lastQuery.directory,...(lastQuery.query?{query:lastQuery.query}:{}),...(pageCursor?{cursor:pageCursor}:{})};
   next.disabled=true;
   try{
    const data=await request(base+'?'+new URLSearchParams(args));if(generation!==epoch||!section.isConnected)return;
    for(const item of data.entries||data.matches||[]){const button=action(item.path+(item.kind==='directory'?'/':''),()=>{if(item.kind==='directory'){directory.value=item.path;query.value='';list()}else read(item.path)});entries.append(button)}
    pageCursor=data.next_cursor;next.disabled=!pageCursor;status.textContent='Current directory only. '+(pageCursor?'More entries available.':'End of listing.');
   }catch(error){if(generation===epoch)status.textContent=error.message}
  };
  const next=action('More file entries',()=>list(true));next.disabled=true;
  const newPath=el('input');newPath.placeholder='Exact new project-relative filename';newPath.setAttribute('aria-label','New file path');
  section.append(el('h2','section-title','Project files'),el('p','muted','Discover exact paths, read the current version, then propose a change for approval.'),directory,query,action('List or find files',()=>list()),next,newPath,action('Draft new text file',()=>read(newPath.value,0,null,true)),status,entries,reader);panel.append(section);list();
 };
 document.addEventListener('DOMContentLoaded',()=>{
  const dialog=document.createElement('dialog'),form=document.createElement('form'),title=document.createElement('h2'),input=document.createElement('input'),label=document.createElement('label'),button=document.createElement('button'),notice=document.createElement('p');
  title.textContent='Open your Logis workspace';label.textContent='Scoped access token';input.type='password';input.required=true;input.autocomplete='off';input.setAttribute('aria-label','Scoped access token');button.textContent='Connect';notice.textContent='The token is kept in memory until this tab closes. Use an existing scoped credential.';label.append(input);form.append(title,label,notice,button);dialog.append(form);document.body.append(dialog);dialog.addEventListener('cancel',e=>e.preventDefault());dialog.showModal();
  const finishAuth=()=>{input.value='';dialog.close();dialog.remove();resolveAuth()};
  form.onsubmit=async e=>{e.preventDefault();button.disabled=true;credential=input.value;try{await request('/api/projects',undefined,{},'GET',false);finishAuth()}catch(error){credential='';notice.textContent=error.message}finally{button.disabled=false}};
  const sessionButton=document.createElement('button');sessionButton.type='button';sessionButton.textContent='Use paired device';form.append(sessionButton);
  sessionButton.onclick=async()=>{sessionButton.disabled=true;try{credential='';const session=await request('/api/device/session',undefined,{},'GET',false);if(session.status!=='paired'||!session.csrf)throw Error('No existing paired device session');csrf=session.csrf;await request('/api/projects',undefined,{},'GET',false);finishAuth()}catch(error){csrf='';notice.textContent=error.message}finally{sessionButton.disabled=false}};
  // Keep original navigation and layout; mark incomplete capabilities explicitly.
  for(const id of ['newChat','newProject','attach','attachPanel','checkpoint','checks','modelChoice','taskSelect','refreshTasks','style','preview','powers']){
   const node=document.getElementById(id);if(node){node.disabled=true;node.title='Not connected in this canonical UI integration';}
  }
  document.querySelector('.task-selection').classList.add('hidden');
  document.getElementById('modelInfo').textContent='Current local provider';
  document.getElementById('contextBadge').textContent='Bounded context';
  document.querySelectorAll('#settingsDialog .help').forEach(n=>n.textContent='Model setup and optional integrations are deferred. This interface uses existing scoped projects, durable runs and canonical records.');
  document.querySelector('#settingsDialog .setting-row strong').textContent='Existing provider configuration';
  health=async()=>{try{await request('/health');$('health').textContent='Workspace connected';$('settingsHealth').textContent='Canonical API connected; model readiness checked per run';$('healthDot').classList.add('online');$('settingsContext').textContent='Provider budget checked per request'}catch{$('health').textContent='Workspace disconnected'}};
  loadTaskChoices=async()=>{};
  const originalRender=renderJob;renderJob=()=>{originalRender();$('continue').classList.add('hidden');$('checkpoint').disabled=true;$('checks').disabled=true;$('contextBadge').textContent='Bounded context';if(state?.job)$('elapsed').textContent=state.job.phase==='queued'?'Waiting for model slot':''};
  const options=$('more').onclick;$('more').onclick=()=>{options();$('optionsDialog').dataset.version=state?.version||''};
  $('export').textContent='Export canonical records';$('export').title='Conversation, records, source evidence and run metadata; filesystem bytes and credentials are excluded';
  $('export').onclick=async()=>{if(!current)return;try{const project=current,data=await api('/api/export?id='+encodeURIComponent(project)),blob=new Blob([JSON.stringify(data,null,2)],{type:'application/json'}),url=URL.createObjectURL(blob),link=document.createElement('a');link.href=url;link.download='logis-canonical-export.json';document.body.append(link);link.click();link.remove();URL.revokeObjectURL(url);notify('Canonical records exported. See the manifest for exclusions; this is not a filesystem backup.')}catch(error){showError(error)}};
  $('rename').onclick=async()=>{try{await api('/api/update',{id:current,name:$('renameInput').value,expected_version:Number($('optionsDialog').dataset.version)});$('optionsDialog').close();await refresh();await loadList()}catch(error){showError(error)}};
  const instructionsChanged=$('instructions').oninput;$('instructions').oninput=()=>{if($('instructions').dataset.dirty!=='yes')$('instructions').dataset.version=state?.version||'';instructionsChanged()};
  $('saveInstructions').onclick=async()=>{try{await api('/api/update',{id:current,brief:$('instructions').value,expected_version:Number($('instructions').dataset.version)||state.version});$('instructions').dataset.dirty='no';notify('Project instructions saved');await refresh()}catch(error){showError(error)}};
  const originalEdit=editRecord;editRecord=(kind,item={})=>{originalEdit(kind,item);$('recordForm').dataset.project=item.project_id||current||'';$('recordForm').dataset.version=item.version||''};
  $('recordForm').onsubmit=async e=>{e.preventDefault();try{await api('/api/workspace-item',{kind:$('recordKind').value,id:$('recordId').value||undefined,project_id:$('recordForm').dataset.project,expected_version:Number($('recordForm').dataset.version)||undefined,title:$('recordTitle').value,detail:$('recordDetail').value,status:$('recordStatus').value});$('recordDialog').close();loadView(activeView)}catch(error){notify(error.message)}};
  DESCRIPTIONS.pipelines[1]='Saved workflow plans. Automatic workflow execution is not connected.';
  DESCRIPTIONS.artifacts[1]='Generated build evidence is available in the selected project run panel.';
  DESCRIPTIONS.agents[1]='Agent configuration and model inventory are not connected to this interface.';
  newChat=()=>notify('Select an existing scoped project. Project creation is not connected yet.');
  newProject=newChat;
  const updateCopy=()=>{
   const banner=document.querySelector('.atlas-banner p');if(banner&&banner.textContent!=='Durable queued work with recovery and evidence. Active work counts cover up to 20 current projects.')banner.textContent='Durable queued work with recovery and evidence. Active work counts cover up to 20 current projects.';
  };
  new MutationObserver(updateCopy).observe(document.getElementById('shell'),{childList:true,subtree:true});updateCopy();
 });
})();
