"""Conservative evidence gate, supplementing typed model planning.

English recall patterns only; does not classify every language or mixed intent.
No write authority, no automatic capture and no private context sent externally.
"""
import re
def recall_question(text):
    question=bool(re.search(r'(?i)^\s*(what|which|when|where|who|how|do i|did i|have i|remind me|tell me)',text))
    personal=bool(re.search(r'(?i)\b(my|did i|have i|i prefer|i like|i want|i chose|i decided|we decided|i told you|i asked|remember about me)\b',text))
    recall=bool(re.search(r'(?i)\b(prefer|preference|favorite|favourite|decided|decision|chose|saved|record|recorded|told you|asked you|remember)\b',text))
    return question and personal and recall
def enforce(plan,text,plan_type,action_type,observations=None):
    if observations or plan.actions or not recall_question(text):return plan
    # Re-read active canonical assertions so corrections/deletions supersede
    # stale conversation text. Empty query is bounded by the existing adapter.
    return plan_type(actions=[action_type(tool='memory_recall',query='')])
