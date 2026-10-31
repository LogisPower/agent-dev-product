'use strict';
// Extend the original Logis Tasks view; retain its navigation, cards and approval style.
const originalLogisLoadView = loadView;
loadView = async function(view) {
  await originalLogisLoadView(view);
  if (view !== 'tasks' || activeView !== view) return;
  const panel = el('section', 'view-body');
  panel.append(el('h2', 'section-title', 'Background work'));
  const project = current;
  if (!project) {
    panel.append(el('p', 'muted', 'Open a project to inspect its background work.'));
    $('workspaceView').append(panel);
    return;
  }
  panel.append(el('p', 'muted', 'Saved task state and file evidence. Chat remains separate; a busy model can still delay a model reply.'));
  const state = el('p', 'muted', 'Loading task state…');
  const cards = el('div', 'card-grid');
  let cursor = 0, busy = false, signature = '', tasks = new Map();
  const command = async (actionName, task) => {
    try {
      await api('/api/foundation', {project, action: actionName, task: task.id, version: task.version});
      await refreshTasks();
    } catch (error) { notify(error.message); }
  };
  async function refreshTasks() {
    if (busy || !panel.isConnected || activeView !== 'tasks') return;
    busy = true;
    try {
      const data = await api('/api/foundation?project=' + encodeURIComponent(project) + '&after=' + cursor);
      if (!panel.isConnected) return;
      for (const task of data.tasks) tasks.set(task.id, task);
      cursor = data.next_cursor;
      state.textContent = 'Worker: ' + data.worker + (data.worker_error ? ' · ' + data.worker_error : '') + (data.has_more ? ' · More saved events available; refresh to continue.' : '');
      const next = JSON.stringify([...tasks.values()]);
      if (next !== signature) {
        signature = next;
        cards.replaceChildren();
        for (const task of tasks.values()) {
          const tile = card(task.payload.path || task.kind, 'Attempt ' + task.attempts + ' of ' + task.max_attempts, task.status.replaceAll('_', ' ').toUpperCase());
          const details = el('details');
          details.append(el('summary', '', 'Request and evidence'), el('pre', '', JSON.stringify({id: task.id, request: task.payload, checkpoint: task.checkpoint, result: task.result}, null, 2)));
          tile.append(details);
          for(const dependency of task.dependencies||[]){
            tile.append(el('p','muted','Requires '+dependency.path+' from '+dependency.task+' — '+dependency.status+(dependency.sha256?' | '+dependency.sha256:' | no committed artifact yet')));
          }
          if(task.kind==='file_write'&&!['failed','canceled'].includes(task.status))tile.append(action('Queue read after commit',async()=>{
            try{const result=await api('/api/foundation',{project,action:'submit',key:'verify-'+task.id,kind:'file_read',payload:{path:task.payload.path},dependencies:[{task:task.id,path:task.payload.path}]});notify('Verification task '+result.id+' — '+result.status);await refreshTasks()}catch(error){notify(error.message)}
          }));
          if (task.status === 'approval') {
            tile.append(el('p', 'muted', 'Review the exact file content and expected version above before approving.'));
            tile.append(action('Approve this file change', () => command('approve', task)));
          }
          if (['queued', 'waiting', 'approval', 'running', 'cancel_requested'].includes(task.status)) tile.append(action('Cancel', () => command('cancel', task)));
          if (task.status === 'needs_review') tile.append(action('Inspect file receipt', async () => {
            try {
              const evidence = await api('/api/foundation?project=' + encodeURIComponent(project) + '&action=effect&task=' + task.id);
              details.append(el('pre', '', JSON.stringify(evidence, null, 2))); details.open = true;
              if (evidence.state === 'verified_effect_observed') details.append(action('Accept verified file result', () => command('reconcile', task)));
            } catch (error) { notify(error.message); }
          }));
          cards.append(tile);
        }
      }
      if (!tasks.size) state.textContent += ' · No background tasks for this project.';
    } catch (error) { state.textContent = 'Background work unavailable: ' + error.message; }
    finally { busy = false; }
  }
  const path = el('input'); path.placeholder = 'Project-relative file path'; path.setAttribute('aria-label', 'File to inspect in background');
  panel.append(path, action('Inspect file in background', async () => {
    try {
      await api('/api/foundation', {project, action:'submit', key:crypto.randomUUID(), kind:'file_read', payload:{path:path.value}});
      await refreshTasks();
    } catch (error) { notify(error.message); }
  }), state, action('Refresh background work', refreshTasks), cards);
  $('workspaceView').append(panel);
  if (typeof window.mountLogisProjectFiles === 'function') window.mountLogisProjectFiles(panel, project);
  if (typeof mountDurableRuns === 'function') mountDurableRuns(panel, project);
  if (typeof window.mountLogisLocalWork === 'function') window.mountLogisLocalWork(panel, project);
  await refreshTasks();
  const timer = setInterval(() => {
    if (!panel.isConnected || activeView !== 'tasks') { clearInterval(timer); return; }
    refreshTasks();
  }, 2000);
};
