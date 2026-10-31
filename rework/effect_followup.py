"""Permit a validated explicit edit/move only after matching read evidence.

The original request still passes intent_core.validate; observations never supply
authorization. This only bridges the read-hash precondition of that same request.
"""
import re

def explicit_workspace_plan(text,observations,plan_type,action_type):
    # Deterministic contract for explicit filenames, not a general intent parser.
    # No inferred paths, globbing, shell syntax or external workspace access.
    m=re.fullmatch(r'(?i)\s*(?:please\s+|can you\s+)?move\s+(\S+)\s+to\s+(\S+?)(?:\s+in (?:this |the )?project workspace)?\.?\s*',text)
    if m:
        source,destination=m.groups()
        from workspace_files import relative
        relative(source);relative(destination)
        if not observations:return plan_type(actions=[action_type(tool='workspace_read',path=source)])
        prior=next((r for r in observations if r.get('tool')=='workspace_read' and r.get('status')=='read' and r.get('data',{}).get('path')==source),None)
        if prior:return plan_type(actions=[action_type(tool='workspace_move',path=source,destination=destination,expected_sha256=prior['data']['sha256'])])
    m=re.fullmatch(r'(?i)\s*(?:please\s+)?read\s+(\S+?)(?:\s+and tell me what it says)?\.?\s*',text)
    if m and '/' in m[1] and not observations and not re.match(r'(?i)https?://',m[1]):
        from workspace_files import relative
        relative(m[1]);return plan_type(actions=[action_type(tool='workspace_read',path=m[1])])
    return None

def verify_followup(actions,results,tools):
    writes=[a for a in actions if tools[a.tool].effect=='write']
    if not writes:return
    if len(actions)!=1 or len(writes)!=1:raise ValueError('One explicit mutation only')
    action=writes[0]
    if action.tool not in ('workspace_edit','workspace_move','file_edit'):
        raise ValueError('Read observations cannot authorize a new mutation; send an explicit separate request')
    read_tool='file_read' if action.tool=='file_edit' else 'workspace_read'
    id_key='id' if action.tool=='file_edit' else 'path'
    expected_id=action.file_id if action.tool=='file_edit' else action.path
    if not any(r.get('tool')==read_tool and r.get('status')=='read' and r.get('data',{}).get(id_key)==expected_id and r.get('data',{}).get('sha256')==action.expected_sha256 for r in results):
        raise ValueError('Mutation lacks matching current read receipt; no effect executed')
