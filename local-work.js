'use strict';
window.mountLogisLocalWork = function(parent, project) {
  const panel=el('section','view-body'), status=el('p','muted','Loading local work.'), cards=el('div','card-grid');
  panel.append(el('h2','section-title','Local coding tasks'),el('p','muted','Prepare an exact file edit, review it, then approve local execution. Uncertain work stays available for review.'));
  const path=el('input'), original=el('pre'), before=el('textarea'), after=el('textarea'), dependency=el('input'), artifact=el('input'), notice=el('p','muted');
  path.placeholder='Project-relative file path';path.setAttribute('aria-label','Local edit file');
  before.placeholder='Exact text to replace';before.setAttribute('aria-label','Exact original text');
  after.placeholder='Replacement text';after.setAttribute('aria-label','Replacement text');
  dependency.placeholder='Optional predecessor task ID';dependency.setAttribute('aria-label','Predecessor task ID');
  artifact.placeholder='Required predecessor artifact path';artifact.setAttribute('aria-label','Required artifact path');
  let snapshot=null, cursor=0, refreshing=false, preparing=false, submitting=false, signature='', tasks=new Map(), keys=new Map();
  const base='/api/local-work?project='+encodeURIComponent(project);
  const send=(action,body)=>api('/api/local-work',{project,action,...body});
  const decide=async(action,task)=>{try{if(['local_plan','local_discovery','local_author','local_verify','local_analysis'].includes(task.kind))await api('/api/local-planning',{project,action,task:task.id,version:task.version});else await send(action,{task:task.id,version:task.version});await refresh()}catch(error){notice.textContent=error.message}};
  function render(){
    const next=JSON.stringify([...tasks.values()]);if(next===signature)return;signature=next;
    cards.replaceChildren();
    for(const task of tasks.values()){
      const tile=card(task.kind==='local_analysis'?'Read-only source analysis':task.kind==='local_verify'?'Project verification':task.kind==='local_author'?'New-file proposal':task.kind==='local_discovery'?'Project discovery':task.kind==='local_plan'?'Local plan proposal':task.targets.map(t=>t.path).join(', '),task.plan?task.plan.title+' | Step '+task.plan.position+' of '+task.plan.total:'Task '+task.id,task.status.replaceAll('_',' ').toUpperCase());
      const detail=el('details');detail.append(el('summary','','Exact edit and evidence'),el('pre','',JSON.stringify({plan:task.plan,targets:task.targets,dependencies:task.dependencies,checkpoint:task.checkpoint,result:task.result,artifacts:task.artifacts},null,2)));tile.append(detail);
      if(task.status==='approval')tile.append(action('Approve local edit',()=>decide('approve',task)));
      if(['approval','queued','waiting','running','cancel_requested'].includes(task.status))tile.append(action('Cancel local task',()=>decide('cancel',task)));
      if(['local_plan','local_author'].includes(task.kind)&&task.status==='completed')tile.append(action('Add proposal to mixed plan',()=>{
        if(mixedSelections.length>=8){notice.textContent='At most eight proposals; the server also limits total files to eight.';return}
        if(!mixedSelections.some(item=>item.task===task.id))mixedSelections.push({task:task.id,version:task.version});renderMixed();
      }));
      if(task.kind==='local_author'&&task.status==='completed'){
        tile.append(el('p','muted','Review the complete proposed content in the evidence panel. Saving creates an approval task in Background work; it does not write the file.'));
        tile.append(action('Save new file for review',async()=>{
          try{const result=await api('/api/local-planning',{project,action:'accept-author',task:task.id,version:task.version});detail.append(el('pre','',JSON.stringify(result,null,2)));detail.open=true;notice.textContent='Saved writer '+result.write.id+' and verification '+result.verify.id+'. Refresh Background work above to review and approve the writer.'}catch(error){notice.textContent=error.message}
        }));
        tile.append(action('Inspect new-file workflow',async()=>{
          try{const result=await api('/api/local-planning',{project,action:'author-workflow',task:task.id,version:task.version});detail.append(el('pre','',JSON.stringify(result,null,2)));detail.open=true}catch(error){notice.textContent=error.message}
        }));
      }
      if(task.kind==='local_author'&&['needs_review','failed'].includes(task.status))tile.append(el('p','muted','New-file proposal needs review. No source was written by this request; no automatic retry.'));
      if(task.kind==='local_discovery'&&task.status==='completed'){
        tile.append(el('p','muted',task.result.notice+(task.result.truncated?' Search was truncated.':'')));
        for(const candidate of task.result.candidates){
          tile.append(action('Select '+candidate.path,()=>{const paths=selectedFiles.value.split(/\r?\n/).filter(Boolean);if(!paths.includes(candidate.path)&&paths.length<2)paths.push(candidate.path);selectedFiles.value=paths.join('\n')}));
          tile.append(el('p','muted',candidate.path+(candidate.blocked_by.length?' | Unfinished work: review required.':'')+(candidate.completed_unchanged?' | Already completed at this version.':'')));
        }
        tile.append(action('Plan selected discoveries',async()=>{
          if(!planningEnabled){notice.textContent='Local planner is not connected.';return}
          try{const value=await api('/api/local-planning',{project,action:'from-discovery',task:task.id,version:task.version,goal:goal.value,paths:selectedFiles.value.split(/\r?\n/).map(p=>p.trim()).filter(Boolean),allow_completed:newGoal.checked===true});tasks.set(value.id,value);render();await refresh()}catch(error){notice.textContent=error.message}
        }));
      }
      if(task.kind==='local_analysis'){
        tile.append(el('p','muted','Read-only analysis. Quotes are checked against source; summaries may be wrong. Planning rechecks the source and never approves edits.'));
        if(['failed','canceled','needs_review'].includes(task.status))tile.append(action('Resume saved analysis',()=>decide('resume-analysis',task)));
        if(task.status==='completed')tile.append(action('Plan selected files with this analysis',async()=>{
          try{const value=await api('/api/local-planning',{project,action:'from-analysis',task:task.id,version:task.version,goal:goal.value,paths:selectedFiles.value.split(/\r?\n/).map(p=>p.trim()).filter(Boolean)});tasks.set(value.id,value);render();await refresh()}catch(error){notice.textContent=error.message}
        }));
      }
      if(task.kind==='local_plan'&&task.status==='completed'){
        tile.append(action('Inspect proposal workflow',async()=>{
          try{const value=await api(base+'&action=workflow&task='+encodeURIComponent(task.id));detail.append(el('pre','',JSON.stringify(value,null,2)));detail.open=true}catch(error){notice.textContent=error.message}
        }));
        tile.append(el('p','muted','Proposal generation does not execute edits. Inspect workflow status to see any review tasks created from this proposal.'));
        tile.append(action('Create review tasks from proposal',async()=>{
          try{const result=await api('/api/local-planning',{project,action:'accept',task:task.id,version:task.version});for(const item of result.tasks)tasks.set(item.id,item);render();notice.textContent='Review tasks saved. Each edit still needs approval.';await refresh()}catch(error){notice.textContent=error.message}
        }));
      }
      if(task.status==='needs_review'&&task.kind==='local_exact_edit'){
        tile.append(el('p','muted','No automatic retry. Acceptance checks provider completion and the exact existing file result.'));
        tile.append(action('Accept verified local result',()=>decide('reconcile',task)));
      }
      if(task.kind==='local_plan'&&['needs_review','failed'].includes(task.status))tile.append(el('p','muted','Proposal generation needs review. It has not edited source files or queued execution tasks. No automatic retry.'));
      cards.append(tile);
    }
  }
  async function refresh(){
    if(refreshing||!panel.isConnected)return;refreshing=true;
    try{const data=await api(base+'&after='+cursor);if(!panel.isConnected)return;
      for(const task of data.tasks)tasks.set(task.id,task);cursor=data.next_cursor;render();
      status.textContent='Local worker: '+data.worker+(data.worker_error?' | '+data.worker_error:'')+(data.worker==='stopped'?' | Approved jobs wait until the local worker is running.':'')+(data.has_more?' | More saved events available; refresh to continue.':'');
      planningEnabled=data.planning_enabled===true;propose.disabled=!planningEnabled||proposing;
    }catch(error){status.textContent='Local coding tasks unavailable: '+error.message}
    finally{refreshing=false}
  }
  const load=action('Load current file',async()=>{
    if(preparing)return;preparing=true;load.disabled=true;snapshot=null;const selected=path.value;
    try{const value=await api(base+'&action=prepare&path='+encodeURIComponent(selected));
      if(path.value!==selected||!panel.isConnected)return;
      if(value.status!=='ok'){snapshot=null;notice.textContent=value.next_action||'File missing.';return}
      snapshot=value;original.textContent=value.content;notice.textContent='Current version: '+value.sha256+'. Enter one unique exact replacement below.';
    }catch(error){notice.textContent=error.message}
    finally{preparing=false;load.disabled=false}
  });
  function currentDraft(){
    if(!snapshot||snapshot.path!==path.value)throw Error('Load the current file first.');
    if(!before.value||before.value===after.value||snapshot.content.split(before.value).length!==2)throw Error('Choose one unique original passage and a different replacement.');
    if(Boolean(dependency.value)!==Boolean(artifact.value))throw Error('Supply both the predecessor task and its required artifact path.');
    return {edits:[{path:snapshot.path,expected_sha256:snapshot.sha256,old:before.value,new:after.value}],dependencies:dependency.value?[{task:dependency.value,path:artifact.value}]:[]};
  }
  const queue=action('Submit for local approval',async()=>{
    if(submitting)return;let draft;
    try{draft=currentDraft()}catch(error){notice.textContent=error.message;return}
    const fingerprint=JSON.stringify(draft);if(!keys.has(fingerprint))keys.set(fingerprint,crypto.randomUUID());
    submitting=true;queue.disabled=true;
    try{const task=await send('submit',{key:keys.get(fingerprint),...draft});tasks.set(task.id,task);render();notice.textContent='Saved task '+task.id+'. Review its exact edit before approving.';await refresh()}
    catch(error){notice.textContent=error.message+' Your draft and request identity are retained.'}
    finally{submitting=false;queue.disabled=false}
  });
  const planTitle=el('input'),planList=el('div','card-grid');planTitle.placeholder='Plan title';planTitle.setAttribute('aria-label','Local plan title');
  let planned=[],savingPlan=false;const planKeys=new Map();
  function renderPlan(){
    planList.replaceChildren();
    planned.forEach((edit,index)=>{
      const row=el('div','card');row.append(el('p','','Step '+(index+1)+': '+edit.path+(index?' | Waits for the previous verified file.':'')));
      const detail=el('details');detail.append(el('summary','','Review planned edit'),el('pre','',JSON.stringify(edit,null,2)));row.append(detail);
      row.append(action('Remove step '+(index+1),()=>{planned.splice(index,1);renderPlan()}));planList.append(row);
    });
  }
  const add=action('Add edit to plan',()=>{
    try{const draft=currentDraft();
      if(draft.dependencies.length)throw Error('Plans link their own steps; clear the external predecessor fields first.');
      if(planned.length>=8)throw Error('A plan supports at most eight steps.');
      if(planned.some(edit=>edit.path.toLowerCase()===draft.edits[0].path.toLowerCase()))throw Error('Use one planned edit per file.');
      planned.push(draft.edits[0]);renderPlan();notice.textContent='Added to the draft plan. Nothing has been submitted or approved.';
    }catch(error){notice.textContent=error.message}
  });
  const savePlan=action('Submit plan for review',async()=>{
    if(savingPlan)return;
    if(!planTitle.value.trim()||!planned.length){notice.textContent='Give the plan a title and add at least one exact edit.';return}
    const draft={title:planTitle.value,steps:planned.map((edit,index)=>({name:'step-'+(index+1),edit,after:index?['step-'+index]:[]}))};
    const fingerprint=JSON.stringify(draft);if(!planKeys.has(fingerprint))planKeys.set(fingerprint,crypto.randomUUID());
    savingPlan=true;savePlan.disabled=true;
    try{const result=await send('plan',{key:planKeys.get(fingerprint),...draft});for(const task of result.tasks)tasks.set(task.id,task);render();notice.textContent='Saved plan '+result.id+'. Review and approve each step separately.';await refresh()}
    catch(error){notice.textContent=error.message+' The plan draft and request identity are retained.'}
    finally{savingPlan=false;savePlan.disabled=false}
  });
  const preview=el('details');preview.append(el('summary','','Current file'),original);
  const goal=el('textarea'),selectedFiles=el('textarea');goal.placeholder='Describe a small change for the local model to plan';goal.setAttribute('aria-label','Local planning goal');
  selectedFiles.placeholder='One or two project-relative file paths, one per line';selectedFiles.setAttribute('aria-label','Files for local planning');
  let planningEnabled=false,proposing=false;const proposalKeys=new Map();
  const propose=action('Ask local model for a plan',async()=>{
    if(!planningEnabled||proposing){notice.textContent='The local text-only planner is not connected or is handling this request.';return}
    const draft={goal:goal.value,paths:selectedFiles.value.split(/\r?\n/).map(p=>p.trim()).filter(Boolean)};
    if(!draft.goal.trim()||!draft.paths.length||draft.paths.length>2){notice.textContent='Enter a goal and select one or two existing files.';return}
    const fingerprint=JSON.stringify(draft);if(!proposalKeys.has(fingerprint))proposalKeys.set(fingerprint,crypto.randomUUID());proposing=true;propose.disabled=true;
    try{const task=await api('/api/local-planning',{project,action:'propose',key:proposalKeys.get(fingerprint),...draft});tasks.set(task.id,task);render();notice.textContent='Planning request saved. Generated edits must be reviewed and approved separately.';await refresh()}
    catch(error){notice.textContent=error.message+' The goal and request identity are retained.'}
    finally{proposing=false;propose.disabled=!planningEnabled}
  });propose.disabled=true;
  const analysisPath=el('input');analysisPath.setAttribute('aria-label','Source for read-only analysis');analysisPath.placeholder='One project-relative text file, at most 32 KB';
  const analysisKeys=new Map();let analyzing=false;
  const analyze=action('Analyze larger source locally',async()=>{
    if(!planningEnabled||analyzing){notice.textContent='Connect the local planner before analysis.';return}
    const draft={goal:goal.value,path:analysisPath.value};
    if(!draft.goal.trim()||!draft.path.trim()){notice.textContent='Enter a question and source path.';return}
    const fingerprint=JSON.stringify(draft);if(!analysisKeys.has(fingerprint))analysisKeys.set(fingerprint,crypto.randomUUID());analyzing=true;analyze.disabled=true;
    try{const task=await api('/api/local-planning',{project,action:'analyze',key:analysisKeys.get(fingerprint),...draft});tasks.set(task.id,task);render();notice.textContent='Read-only analysis queued: at most three serial model calls. No files will be edited.';await refresh()}
    catch(error){notice.textContent=error.message+' Analysis draft and request identity retained.'}
    finally{analyzing=false;analyze.disabled=false}
  });

  const newPath=el('input');newPath.placeholder='New project-relative filename in an existing directory';newPath.setAttribute('aria-label','New file path');
  const authorKeys=new Map();let authoring=false;
  const author=action('Draft a new file locally',async()=>{
    if(!planningEnabled||authoring){notice.textContent='Local text-only planner must be connected.';return}
    const draft={goal:goal.value,path:newPath.value,context_paths:selectedFiles.value.split(/\r?\n/).map(p=>p.trim()).filter(Boolean)};
    if(!draft.goal.trim()||!draft.path||draft.context_paths.length>2){notice.textContent='Enter a goal, a new filename and at most two existing context files.';return}
    const fingerprint=JSON.stringify(draft);if(!authorKeys.has(fingerprint))authorKeys.set(fingerprint,crypto.randomUUID());authoring=true;author.disabled=true;
    try{const task=await api('/api/local-planning',{project,action:'author',key:authorKeys.get(fingerprint),...draft});tasks.set(task.id,task);render();notice.textContent='New-file proposal queued. Content review and file approval remain separate.';await refresh()}catch(error){notice.textContent=error.message+' Draft and request identity retained.'}finally{authoring=false;author.disabled=false}
  });
  const mixedTitle=el('input'),manualReview=el('input'),mixedDraft=el('div'),mixedEvidence=el('pre');mixedTitle.setAttribute('aria-label','Mixed plan title');mixedTitle.placeholder='Mixed create/edit plan title';manualReview.type='checkbox';manualReview.setAttribute('aria-label','Manual review for unsupported languages');
  const manualLabel=el('label');manualLabel.append(manualReview,el('span','','I will manually review files without a supported syntax parser'));
  let mixedSelections=[],savingMixed=false;const mixedKeys=new Map();
  function renderMixed(){mixedDraft.replaceChildren();mixedSelections.forEach((item,index)=>{const row=el('p','','Step group '+(index+1)+': '+item.task);row.append(action('Remove proposal '+(index+1),()=>{mixedSelections.splice(index,1);renderMixed()}));mixedDraft.append(row)})}
  const saveMixed=action('Validate and save mixed plan',async()=>{
    if(savingMixed)return;if(!mixedTitle.value.trim()||!mixedSelections.length){notice.textContent='Name the mixed plan and add completed proposals from their cards.';return}
    const draft={title:mixedTitle.value,selections:mixedSelections.map(item=>({...item})),allow_unsupported:manualReview.checked===true};const fingerprint=JSON.stringify(draft);if(!mixedKeys.has(fingerprint))mixedKeys.set(fingerprint,crypto.randomUUID());savingMixed=true;saveMixed.disabled=true;
    try{const result=await api('/api/local-planning',{project,action:'mixed',key:mixedKeys.get(fingerprint),...draft});mixedEvidence.textContent=JSON.stringify(result,null,2);notice.textContent='Mixed plan saved atomically. Review syntax evidence and approve each writer separately in Background work.'}catch(error){notice.textContent=error.message+' Draft and request identity retained.'}finally{savingMixed=false;saveMixed.disabled=false}
  });
  const inspectMixed=action('Inspect saved mixed plans',async()=>{try{mixedEvidence.textContent=JSON.stringify(await api('/api/projects/'+encodeURIComponent(project)+'/local-planning/mixed'),null,2)}catch(error){notice.textContent=error.message}});
  const verifyPaths=el('textarea');verifyPaths.setAttribute('aria-label','Files for project verification');verifyPaths.placeholder='Up to eight project-relative paths, one per line';let verifying=false;const verificationKeys=new Map();
  const verifyFiles=action('Start current-file verification',async()=>{
    if(verifying)return;const paths=verifyPaths.value.split(/\r?\n/).map(p=>p.trim()).filter(Boolean);if(!paths.length||paths.length>8){notice.textContent='Choose one to eight current files.';return}
    const fingerprint=JSON.stringify(paths);if(!verificationKeys.has(fingerprint))verificationKeys.set(fingerprint,crypto.randomUUID());verifying=true;verifyFiles.disabled=true;
    try{const task=await api('/api/local-planning',{project,action:'verify',key:verificationKeys.get(fingerprint),paths});tasks.set(task.id,task);render();verificationKeys.delete(fingerprint);notice.textContent='Read-only syntax verification queued. Inspect its evidence card when complete; another explicit click starts a fresh snapshot.';await refresh()}catch(error){notice.textContent=error.message+' Selection and request identity retained.'}finally{verifying=false;verifyFiles.disabled=false}
  });
  const query=el('input'),directory=el('input'),newGoal=el('input');query.setAttribute('aria-label','Discovery query');query.placeholder='Literal filename or text to find';directory.setAttribute('aria-label','Discovery directory');directory.placeholder='Optional project-relative directory';newGoal.type='checkbox';newGoal.setAttribute('aria-label','New goal for completed files');
  const discoveryKeys=new Map();let discovering=false;
  const discover=action('Discover project files',async()=>{
    if(discovering)return;const draft={query:query.value,directory:directory.value};if(!draft.query.trim()){notice.textContent='Enter a literal discovery query.';return}
    const fingerprint=JSON.stringify(draft);if(!discoveryKeys.has(fingerprint))discoveryKeys.set(fingerprint,crypto.randomUUID());discovering=true;discover.disabled=true;
    try{const task=await api('/api/local-planning',{project,action:'discover',key:discoveryKeys.get(fingerprint),...draft});tasks.set(task.id,task);render();notice.textContent='Read-only discovery saved. Select candidates after the worker finishes. Repeating this request returns the saved snapshot.';await refresh()}catch(error){notice.textContent=error.message+' Discovery draft and request identity retained.'}finally{discovering=false;discover.disabled=false}
  });
  const completedLabel=el('label');completedLabel.append(newGoal,el('span','','New goal for previously completed files'));
  const evidence=el('pre'),history=el('details');history.append(el('summary','','Saved work and current file evidence'),evidence);
  const inspect=action('Check existing work before planning',async()=>{
    try{const value=await api(base+'&action=context&path='+encodeURIComponent(path.value));evidence.textContent=JSON.stringify(value,null,2);history.open=true}
    catch(error){notice.textContent=error.message}
  });
  panel.append(el('h3','section-title','Discover project files'),query,directory,discover,el('p','muted','Read-only bounded snapshot: at most eight directories and 24 small files. Narrow the directory if incomplete.'),completedLabel,el('h3','section-title','Plan a change locally'),goal,selectedFiles,propose,analysisPath,analyze,el('p','muted','Larger-source analysis saves completed chunks. At most 32 KB, three calls and 90 seconds per call. Resume reuses saved results; uncertain calls require review. Selected edit files remain limited to 12 KB total.'),newPath,author,el('p','muted','Planning reads selected files and proposes edits. It cannot approve or execute them. Requires a connected local planner. New files additionally require the approved Foundation writer, stay below 16 KB, and cannot overwrite existing files.'),path,load,preview,inspect,history,before,after,dependency,artifact,queue,add,el('h3','section-title','Draft local plan'),el('p','muted','Add up to eight files. Each step waits for the previous step’s verified artifact. Saving a plan does not approve it.'),planTitle,planList,savePlan,el('h3','section-title','Mixed create/edit plan'),el('p','muted','Add completed proposals from their cards in execution order. Python, JSON, JavaScript and TypeScript receive syntax checks only; generated code is never executed. File effects are sequential and individually approved, not an all-files atomic commit.'),mixedTitle,manualLabel,mixedDraft,saveMixed,inspectMixed,mixedEvidence,el('h3','section-title','Verify current project files'),el('p','muted','Checks selected versions only, at most eight files and 64 KB. No model, imports, package scripts or generated tests run. TypeScript type-checking and JSX/TSX are not supported.'),verifyPaths,verifyFiles,notice,status,action('Refresh local tasks',refresh),cards);parent.append(panel);refresh();
  const timer=setInterval(()=>{if(!panel.isConnected){clearInterval(timer);return}refresh()},2000);
};
