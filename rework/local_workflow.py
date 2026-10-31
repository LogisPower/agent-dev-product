"""Read-only proposal-to-plan status, recoverable without a provider connection."""
import re
from local_work_plan import plan_identifier


def workflow(loop,project,proposal_id):
    if not isinstance(proposal_id,str) or not re.fullmatch('[a-f0-9]{32}',proposal_id):raise ValueError('Explicit proposal ID required')
    proposal=loop.ledger.get(project,proposal_id)
    if proposal['kind']!='local_plan':raise ValueError('Not a proposal task')
    plan_id=plan_identifier(project,'proposal:'+proposal_id)
    with loop.ledger.connection() as connection:
        rows=connection.execute('SELECT id FROM jobs WHERE project=? AND request_key LIKE ? ORDER BY created,id LIMIT 9',(project,'plan:'+plan_id+':%')).fetchall()
    if len(rows)>8:raise ValueError('Workflow exceeds expected plan bound')
    tasks=[loop.ledger.get(project,row['id']) for row in rows]
    states={task['status'] for task in tasks}
    phase='proposal_ready' if proposal['status']=='completed' else 'planning_'+proposal['status']
    if tasks:
        if 'needs_review' in states:phase='execution_review'
        elif 'failed' in states:phase='execution_failed'
        elif 'cancel_requested' in states:phase='cancellation_requested'
        elif 'canceled' in states:phase='execution_canceled_or_blocked'
        elif 'approval' in states:phase='awaiting_approval'
        elif 'running' in states:phase='executing'
        elif states=={'completed'}:phase='completed'
        else:phase='waiting'
    return {'proposal':proposal,'plan_id':plan_id if tasks else None,'tasks':tasks,'phase':phase,
        'read_only':True,'automatic_retry':False,'completion_evidence':'Recorded task/artifact evidence; current bytes are not rechecked by this status query.'}
