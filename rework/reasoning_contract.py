"""Grounded conversation contract. A prompt is not a factual verification engine."""
import re
from harness_context import assemble
CONTRACT=assemble('intent')[0]

def conversation_messages(history):
    return [{'role':'system','content':CONTRACT}]+[{'role':x['role'],'content':x['content']} for x in history if x['role'] in ('user','assistant')]

def audit_reply(text):
    # Narrow warning, not a complete semantic verifier. Never label facts verified.
    suspect=bool(re.search(r'\bI (?:have )?(?:ran|executed|deployed|searched|browsed|saved (?:the |your )?memor|verified (?:online|the current))',text,re.I))
    evidence={'mode':'no_tool_reply','external_fact_verification':'not_run','tool_execution':'not_run','task_completion':'not_asserted','unsupported_action_claim_detected':suspect,'contract_version':1}
    if suspect:text='[Unverified action claim: this reply has no supporting tool receipt. Treat the following reply as unverified.]\n\n'+text
    return text,evidence
