/* Original Logis cards and navigation backed by scoped canonical evidence. */
document.addEventListener('DOMContentLoaded',()=>{
 const previous=loadView, supported=new Set(['inbox','memory','activity','timeline','artifacts','agents','settings','skills','projects']);let generation=0;
 const evidence=value=>{const node=el('details');node.append(el('summary','','Inspect evidence'),el('pre','',JSON.stringify(value,null,2)));return node};
 loadView=async function(view){
  if(!supported.has(view)){generation++;return previous(view)}
  return render(view,current);
 };
 async function render(view,project){
  const token=++generation,host=$('workspaceView');host.replaceChildren();
  const heading=el('section','view-heading'),body=el('div','view-body'),selector=el('select');selector.setAttribute('aria-label','Evidence project');
  heading.append(el('span','eyebrow','YOUR PRIVATE WORKSPACE'),el('h1','',DESCRIPTIONS[view][0]),el('p','muted','Canonical evidence for one explicitly selected project.'),selector,action('Refresh view',()=>render(view,selector.value||project)));host.append(heading,body);
  const valid=()=>generation===token&&activeView===view&&body.isConnected;
  try{
   const projects=await api('/api/projects');if(!valid())return;
   if(view==='projects'){
    selector.remove();body.append(el('p','muted','Existing scoped projects. Creating a project with new access remains unavailable.'));
    for(const row of projects){const tile=card(row.name,'Saved canonical project',row.kind);tile.append(action('Open',()=>select(row.id)),action('Project settings',async()=>{await select(row.id);setView('settings')}),action('Move to Trash',async()=>{try{await trashConversation(row.id);if(valid())render(view,null)}catch(error){notify(error.message)}}));body.append(tile)}
    if(!projects.length)body.append(el('p','muted','No active projects in this credential scope.'));return;
   }
   selector.add(new Option('Choose a project',''));for(const row of projects)selector.add(new Option(row.name,row.id));selector.value=projects.some(x=>x.id===project)?project:'';
   selector.onchange=()=>render(view,selector.value);project=selector.value;
   if(!project){body.append(el('p','muted','Choose an existing scoped project to inspect its records.'));return}
   const base='/api/projects/'+encodeURIComponent(project);
   if(view==='inbox'){
    body.append(el('p','muted','File approvals, interrupted work and artifact dependencies for this project. Review actions remain in Tasks. External approval services are not connected.'));
    const state=el('p','muted','Loading saved work.'),cards=el('div','card-grid'),tasks=new Map();let cursor=0,busy=false;
    const more=action('Load saved work',refresh);
    body.append(state,cards,more);
    async function refresh(){
     if(busy||!valid())return;busy=true;more.disabled=true;
     try{
      const page=await api(base+'/foundation?after='+cursor);if(!valid())return;
      for(const task of page.tasks)tasks.set(task.id,task);
      cursor=page.next_cursor;cards.replaceChildren();let count=0;
      for(const task of tasks.values()){
       const blocked=['waiting','queued','approval'].includes(task.status)?(task.dependencies||[]).filter(dep=>dep.status!=='completed'||!dep.sha256):[];
       if(!['approval','needs_review'].includes(task.status)&&!blocked.length)continue;
       count++;
       const label=task.status==='approval'?'APPROVAL REQUIRED':task.status==='needs_review'?'RECOVERY REVIEW':'WAITING FOR ARTIFACT';
       const tile=card(task.payload.path||task.kind,task.status==='needs_review'?'Execution was interrupted. Inspect saved evidence before accepting a result or retrying.':'Review the saved request and its committed artifact dependencies.',label);
       tile.append(evidence({id:task.id,status:task.status,request:task.payload,checkpoint:task.checkpoint,result:task.result,dependencies:task.dependencies}));
       for(const dep of blocked)tile.append(el('p','muted','Requires '+dep.path+' from '+dep.task+' - '+dep.status+(dep.sha256?'':' | no committed artifact yet')));
       tile.append(action('Review in Tasks',async()=>{if(!valid())return;try{await select(project);setView('tasks')}catch(error){notify(error.message)}}));cards.append(tile);
      }
      state.textContent=count+' items in loaded task state. Worker: '+page.worker+(page.worker_error?' | '+page.worker_error:'')+(page.has_more?' | More saved events remain.':'');
      if(!count)cards.append(el('p','muted',page.has_more?'No review items in these pages. Load more saved events.':'No pending approvals, recovery reviews or blocked dependencies in loaded task state.'));
      more.textContent=page.has_more?'Load more saved events':'Refresh inbox';
     }catch(error){if(valid())state.textContent='Inbox unavailable: '+error.message}
     finally{busy=false;if(valid())more.disabled=false}
    }
    await refresh();
   }else if(view==='memory'){
    const memory=await api(base+'/memory');if(!valid())return;
    body.append(el('h2','section-title','Confirmed source-backed memories'),el('p','muted','Only confirmed records with current source evidence appear here. This view does not invoke a recall model or automatically capture memories.'));
    for(const record of memory){const tile=card(record.payload.title,record.payload.detail,record.kind);tile.append(action('Inspect sources',async()=>{try{const data=await api('/api/objects/'+encodeURIComponent(record.id)+'/evidence');if(valid())tile.append(evidence(data))}catch(error){notify(error.message)}}));body.append(tile)}
    if(!memory.length)body.append(el('p','muted','No confirmed memories with current evidence.'));
    body.append(el('h2','section-title','Conversation sources'));
    const messages=el('div');let cursor=-1,busy=false;const more=action('Load conversation messages',async()=>{if(busy)return;busy=true;more.disabled=true;try{const page=await api(base+'/conversation?after='+cursor);if(!valid())return;for(const row of page.messages){const tile=card(row.role,row.content,'Message '+row.legacy_index);tile.append(el('small','muted','Source '+row.source_id));messages.append(tile)}cursor=page.next_cursor;more.disabled=!page.has_more;more.textContent=page.has_more?'More source messages':'End of conversation'}catch(error){if(valid()){notify(error.message);more.disabled=false}}finally{busy=false}});body.append(messages,more);
   }else if(view==='activity'||view==='timeline'){
    body.append(el('p','muted','Durable event feed; records appear after the outbox projection runs. This is not an inferred model activity log.'));
    let cursor=0,busy=false;const rows=el('div'),more=action('Load events',async()=>{if(busy)return;busy=true;more.disabled=true;try{const data=await api('/api/events?project='+encodeURIComponent(project)+'&after='+cursor);if(!valid())return;for(const row of data.events)rows.append(card(row.event_type,'Object '+row.object_id+' | version '+(row.record_version??'unavailable'),new Date(row.created_at).toLocaleString()));cursor=data.next_cursor;more.disabled=!data.has_more;more.textContent=data.has_more?'More events':'End of available events'}catch(error){if(valid()){notify(error.message);more.disabled=false}}finally{busy=false}});body.append(rows,more);
   }else if(view==='artifacts'){
    const runs=await api(base+'/builds');if(!valid())return;
    body.append(el('p','muted','Saved offline-build evidence. Preview URLs from other services are not opened automatically. Scoped project file editing remains in Tasks.'));
    for(const run of runs){const p=run.payload,tile=card(p.file||'Offline build',p.sha256?'SHA-256 '+p.sha256:p.notice||'No committed artifact',run.status);tile.append(evidence({id:run.id,status:run.status,sha256:p.sha256,bytes:p.bytes,checks:p.checks,created_at:p.created_at}));body.append(tile)}
    if(!runs.length)body.append(el('p','muted','No saved build runs for this project.'));
   }else if(view==='skills'){
    const [saved,capabilities]=await Promise.all([api('/api/workspace?view=skills'),api(base+'/harness/capabilities')]);if(!valid())return;
    body.append(el('p','muted','Reusable instructions are saved records. Tool registration is not a health check or permission grant.'));
    body.append(action('Add reusable instruction',()=>{editRecord('skills');$('recordForm').dataset.project=project},true));
    for(const row of saved.records.filter(x=>x.project_id===project)){const tile=card(row.title,row.detail,row.status);tile.append(action('Edit',()=>editRecord('skills',row)));body.append(tile)}
    body.append(el('h2','section-title','Registered capabilities'));for(const [name,tool] of Object.entries(capabilities.tools||{})){const tile=card(name,tool.description,tool.registered?'REGISTERED':'UNAVAILABLE');tile.append(evidence(tool));body.append(tile)}
   }else if(view==='agents'){
    const [records,dispatch]=await Promise.all([api('/api/workspace?view=agents'),api(base+'/dispatch')]);if(!valid())return;
    body.append(el('p','muted','Saved role definitions do not start agents. The dispatcher uses one shared model slot.'));
    body.append(action('Add agent role',()=>{editRecord('agents');$('recordForm').dataset.project=project},true));
    for(const row of records.filter(x=>x.project_id===project)){const tile=card(row.title,row.detail,row.status);tile.append(action('Edit role',()=>editRecord('agents',row)));body.append(tile)}
    body.append(card('Dispatcher',dispatch.error_type||'Current worker state',dispatch.worker));for(const run of dispatch.runs){const tile=card(run.kind,run.notice||run.id,run.phase==='queued'?'queued':run.status);tile.append(evidence(run));body.append(tile)}
   }else if(view==='settings'){
    const [meta,models]=await Promise.all([api(base+'/settings'),api(base+'/models')]);if(!valid())return;
    body.append(card('Provider configuration',models.health,'READ ONLY'),evidence(models));
    const form=el('form'),name=el('input'),brief=el('textarea'),sourceLabel=el('p','muted','Context sources: only selected, scoped projects are included.'),sources=el('div'),save=el('button','atlas-primary','Save project settings');
    name.value=meta.name;name.maxLength=80;name.required=true;name.setAttribute('aria-label','Project name');brief.value=meta.brief;brief.maxLength=12000;brief.rows=6;brief.setAttribute('aria-label','Project brief');
    const chosen=new Set(meta.context_policy.sources||[]);for(const p of projects.filter(x=>x.id!==project)){const label=el('label','inline-check'),box=el('input');box.type='checkbox';box.checked=chosen.has(p.id);box.onchange=()=>box.checked?chosen.add(p.id):chosen.delete(p.id);label.append(box,document.createTextNode(p.name));sources.append(label)}
    form.append(el('h2','section-title','Project metadata'),name,brief,sourceLabel,sources,save);form.onsubmit=async e=>{e.preventDefault();save.disabled=true;try{await api('/api/update',{id:project,expected_version:meta.version,name:name.value,brief:brief.value,context_policy:{sources:[...chosen],learning:meta.context_policy.learning!==false}});notify('Project settings saved');if(valid())render(view,project)}catch(error){notify(error.message);save.disabled=false}};body.append(form);
    body.append(el('p','muted','Folder access, provider setup, account storage and external integrations are not changed here. Appearance controls remain in the original sidebar settings.'));
   }
  }catch(error){if(valid())body.append(card('Unavailable',error.message,'NO CHANGE MADE'))}
 }
});
