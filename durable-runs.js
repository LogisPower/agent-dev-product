'use strict';
// Uses original Logis card/button helpers; canonical backend is explicitly detected.
async function mountDurableRuns(panel, project) {
  const base='/api/projects/'+encodeURIComponent(project);
  let initial;
  try { initial=await api(base+'/dispatch'); } catch { return; }
  const section=el('section','view-body');
  section.append(el('h2','section-title','AI work'));
  const status=el('p','muted'),cards=el('div','card-grid');
  const prompt=el('textarea');prompt.placeholder='Describe a small offline app to build';prompt.setAttribute('aria-label','Background build request');
  let buildRequest=null;
  const queueBuild=action('Queue offline build',async()=>{
    if(queueBuild.disabled)return;
    const text=prompt.value;
    if(!buildRequest||buildRequest.prompt!==text)buildRequest={key:crypto.randomUUID(),prompt:text};
    queueBuild.disabled=true;
    try {
      await api(base+'/builds',{prompt:text},{'Idempotency-Key':buildRequest.key});
      buildRequest=null;if(prompt.value===text)prompt.value='';await refresh();
    }catch(error){notify(error.message)}finally{queueBuild.disabled=false}
  });
  section.append(prompt,queueBuild,status,cards);panel.append(section);
  let busy=false,signature='';
  async function refresh(data) {
    if(busy||!section.isConnected)return;busy=true;
    try {
      data=data||await api(base+'/dispatch');
      status.textContent='Worker: '+data.worker+'. One model slot; status remains available while generation is busy.';
      const next=JSON.stringify(data.runs);if(signature===next)return;signature=next;cards.replaceChildren();
      for(const run of data.runs){
        const tile=card(run.kind==='local-build'?'Offline build':'Conversation',run.notice||'Run '+run.id,(run.phase==='queued'?'queued':run.status).replaceAll('_',' ').toUpperCase());
        const evidence=el('details');evidence.append(el('summary','','Run evidence'),el('pre','',JSON.stringify(run,null,2)));tile.append(evidence);
        if(run.status==='running')tile.append(action(run.cancel_requested?'Cancellation requested':'Cancel',async()=>{
          try{await api(base+(run.kind==='local-build'?'/builds/':'/chat/runs/')+run.id+'/cancel',{});await refresh()}catch(error){notify(error.message)}
        }));
        if(run.status==='interrupted')tile.append(el('p','muted','Review saved evidence before retrying. The interrupted action was not automatically repeated.'));
        cards.append(tile);
      }
    }catch(error){status.textContent=error.message}finally{busy=false}
  }
  await refresh(initial);
  const timer=setInterval(()=>{if(!section.isConnected||activeView!=='tasks'){clearInterval(timer);return}refresh()},2000);
}
