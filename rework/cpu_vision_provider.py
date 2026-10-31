"""Bounded resident CPU vision transport; never loads/stops a model.

Deployment must inject a trusted identity collector and pinned measured receipt.
No client input can supply identity, profile, endpoint, process or capacity data.
CPU policy is separate from GPU admission: it cannot claim GPU free space.
"""
import json,time,urllib.request,datetime
from model_bridge import ModelUnavailable,image_receipt
from worker_budget import message_bytes

class CpuVisionProvider:
    def __init__(self,*,measured,collect,lock,send=None,enable_text_worker=False):
        # Detach caller dictionaries; the collector is server-owned, never model code.
        self.measured=json.loads(json.dumps(measured));self.collect=collect;self.lock=lock
        if measured.get('status')!='passed_one_synthetic_vision_task':raise ModelUnavailable('A successful measured CPU receipt is required')
        stamp=datetime.datetime.strptime(measured['started_at'],'%Y%m%dT%H%M%SZ').replace(tzinfo=datetime.timezone.utc)
        self.expires=stamp.timestamp()+86400
        self.send=send or self._send
        self.enable_text_worker=enable_text_worker is True
    @staticmethod
    def _send(payload,timeout):
        request=urllib.request.Request('http://127.0.0.1:8082/v1/chat/completions',data=json.dumps(payload).encode(),headers={'Content-Type':'application/json'})
        with urllib.request.urlopen(request,timeout=timeout) as response:
            raw=response.read(64001)
        if len(raw)>64000:raise ModelUnavailable('Vision response bound exceeded')
        return json.loads(raw)
    def bind(self,role,canceled):
        if role not in ('vision','lightweight') or role=='lightweight' and not self.enable_text_worker:raise ModelUnavailable('Bounded CPU text worker is not enabled; no full planner fallback')
        def invoke(messages,timeout=90,json_output=False,*,image=None):
            if role=='vision' and (not image or json_output):raise ModelUnavailable('This measured CPU profile requires one explicit image and a visible answer')
            if role=='lightweight' and image:raise ModelUnavailable('Text worker cannot accept images')
            if image and (image['pixels']>4096 or image['width']>64 or image['height']>64):
                raise ModelUnavailable('CPU vision profile currently verified only up to64x64; image was not resized or sent')
            if not isinstance(messages,list) or not messages or any(m.get('role') not in ('system','user') or not isinstance(m.get('content'),str) for m in messages):
                raise ModelUnavailable('Bounded vision messages required')
            # Conservative byte bound plus fixed image reserve, not a tokenizer claim.
            text_bytes=message_bytes(messages)
            if text_bytes>(1024 if image else 1536):raise ModelUnavailable('CPU worker context bound exceeded; nothing truncated or sent')
            with self.lock():
                if canceled():raise ModelUnavailable('Canceled before vision dispatch')
                live=self.collect();now=time.time();expected=self.measured
                if now>self.expires:raise ModelUnavailable('CPU measurement expired; no automatic new profiling run')
                if live.get('pid')!=expected.get('pid') or not live.get('process_start_verified'):
                    raise ModelUnavailable('Original CPU process instance not independently verified')
                if live.get('identity')!=expected.get('identity') or not expected.get('identity'):
                    raise ModelUnavailable('CPU model/projector/backend/process identity changed or unknown')
                if live.get('argv')!=expected.get('argv') or not expected.get('argv'):
                    raise ModelUnavailable('CPU launch configuration changed or unknown')
                if not 0<=now-live.get('observed_at',0)<=5:raise ModelUnavailable('Stale CPU capacity observation')
                if live.get('context')!=2048 or live.get('slots')!=[{'id':0,'n_ctx':2048,'is_processing':False}]:
                    raise ModelUnavailable('CPU slot busy or configuration unverified')
                if live.get('available_ram_mib',0)<8192 or live.get('commit_headroom_mib',0)<12288:
                    raise ModelUnavailable('Insufficient CPU memory reserve')
                if live.get('process_working_mib',float('inf'))>8192:raise ModelUnavailable('CPU process exceeds working-set bound')
                prepared=[dict(m) for m in messages]
                if prepared[-1]['role']!='user':raise ModelUnavailable('Image requires final explicit user message')
                if image:prepared[-1]['content']=[{'type':'text','text':prepared[-1]['content']},{'type':'image_url','image_url':{'url':image['data_url']}}]
                payload={'model':'bonsai2-9b-vision','messages':prepared,'max_tokens':96 if image else 256,'temperature':0,'stream':False,'reasoning_effort':'none','chat_template_kwargs':{'enable_thinking':False}}
                if json_output:payload['response_format']={'type':'json_object'}
                body=self.send(payload,min(90 if image else 60,timeout));choice=body['choices'][0];answer=choice['message'].get('content','')
                if canceled():raise ModelUnavailable('Canceled vision result withheld; provider cancellation not claimed')
                if choice.get('finish_reason')!='stop' or not isinstance(answer,str) or not answer.strip():raise ModelUnavailable('Incomplete visible vision answer')
                return answer
        return invoke

def install_verified_cpu_vision(app,*,measured,collector,lock,reasoning,enable_text_worker=False):
    """Explicit staging/deployment hook, never auto-discovery or auto-loading.

    Collector must already hold independently verified pinned identities. Caller
    owns its lifetime and rollback; existing 27B reasoning path is preserved.
    """
    if not getattr(collector,'verified',False):raise ModelUnavailable('CPU collector verification is incomplete')
    provider=CpuVisionProvider(measured=measured,collect=collector,lock=lock,enable_text_worker=enable_text_worker)
    def factory(role,canceled):
        if role=='reasoning':return reasoning
        return provider.bind(role,canceled)
    factory.available_roles=('reasoning','vision','lightweight') if enable_text_worker else ('reasoning','vision')
    app.state.local_model_factory=factory
    app.state.local_model_provenance={'vision':{'measurement':measured['started_at'],'pid':measured['pid'],'identity':measured['identity'],'identity_basis':getattr(collector,'identity_basis','unknown'),'device':'CPU','context':2048,'image_pixels_max':4096,'claim':'one measured synthetic visual task; broad accuracy not established'}}
    if enable_text_worker:app.state.local_model_provenance['lightweight']={**app.state.local_model_provenance['vision'],'image_pixels_max':0,'input_utf8_bytes_max':1536,'output_tokens_max':256,'claim':'Bounded answer-only worker; text acceptance required before production enablement'}
    return provider
