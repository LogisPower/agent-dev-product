"""Bounded observed progress, not a claim of model/OS control."""
import re
import time


class ProgressGuard:
    def __init__(self,clock=time.monotonic):
        self.clock=clock;self.changed=clock();self.sequence=None;self.steps=0
        self.last_tool=-1;self.calls=0;self.signatures={}
    def observe(self,value):
        sequence=value.get('progress_seq');steps=value.get('steps')
        if sequence is None and steps is None:return 'invalid_progress' if self.sequence is not None else None
        if type(sequence) is not int or sequence<0 or (steps is not None and (type(steps) is not int or steps<0)):
            return 'invalid_progress'
        if self.sequence is not None and sequence<self.sequence:return 'progress_regressed'
        if steps is not None and steps<self.steps:return 'progress_regressed'
        if sequence!=self.sequence:self.changed=self.clock();self.sequence=sequence
        if steps is not None:self.steps=steps
        if self.steps>16:return 'step_budget_exceeded'
        calls=value.get('tool_calls',[])
        if not isinstance(calls,list) or len(calls)>32:return 'invalid_progress'
        for call in calls:
            if not isinstance(call,dict) or type(call.get('seq')) is not int or not isinstance(call.get('signature'),str) or not re.fullmatch('[a-f0-9]{64}',call['signature']):return 'invalid_progress'
            seq=call['seq']
            if seq<0 or seq>sequence:return 'invalid_progress'
            if seq<=self.last_tool:continue # Re-reading the same event page is not repetition.
            self.last_tool=seq;self.calls+=1
            signature=call['signature'];self.signatures[signature]=self.signatures.get(signature,0)+1
            if self.signatures[signature]>=4:return 'repeated_tool_call'
            if self.calls>24:return 'tool_budget_exceeded'
        if self.clock()-self.changed>=180:return 'progress_stalled'
        return None
    def evidence(self):return {'progress_seq':self.sequence,'steps':self.steps,'observed_tool_calls':self.calls}
