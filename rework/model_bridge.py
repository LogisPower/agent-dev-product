"""Staged provider boundary. No model loading, environment mutation or fallback."""
import base64,hashlib,struct,os
from model_policy import select,admission

class ModelUnavailable(ValueError):pass

def image_input(value):
    """One bounded PNG supplied by authenticated client, never a fetched URL.

    Header validation bounds input but is not a full PNG decoder certification.
    The model service must retain its own image decoder protections.
    """
    if value is None:return None
    if not isinstance(value,str) or not value.startswith('data:image/png;base64,') or len(value)>1400000:
        raise ValueError('Provide one PNG data image below1MiB; remote URLs are not accepted')
    try:raw=base64.b64decode(value.split(',',1)[1],validate=True)
    except Exception as e:raise ValueError('Invalid image encoding') from e
    if len(raw)>1048576 or len(raw)<33 or raw[:8]!=b'\x89PNG\r\n\x1a\n' or raw[8:16]!=b'\0\0\0\rIHDR':
        raise ValueError('Invalid PNG header or size')
    width,height=struct.unpack('>II',raw[16:24])
    if not 0<width<=2048 or not 0<height<=2048 or width*height>1048576:raise ValueError('Image dimensions exceed bound')
    return {'data_url':value,'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw),'pixels':width*height,'width':width,'height':height}

def image_receipt(image):
    return {k:v for k,v in image.items() if k!='data_url'} if image else None

def for_run(app,role,default_model,*,canceled=lambda:False):
    select(role)
    factory=getattr(app.state,'local_model_factory',None)
    if factory is not None:call=factory(role,canceled)
    elif role=='reasoning':call=default_model
    else:raise ModelUnavailable('Selected9B role unavailable: trusted identity/resource profile not configured; no fallback or model load attempted')
    provider=call
    def call(*args,**kwargs):
        from provider_cancel import cancellation,ProviderCanceled
        if canceled():raise ProviderCanceled('Canceled before provider dispatch')
        with cancellation(canceled):
            answer=provider(*args,**kwargs)
        if canceled():raise ProviderCanceled('Canceled; provider reply withheld')
        return answer
    if getattr(app.state,'local_langchain_enabled',False):
        chain=langchain_runnable(call)
        def invoke(messages,timeout=180,json_output=False,**kwargs):
            if canceled():raise ModelUnavailable('Run canceled before chain execution')
            answer=chain.invoke({'messages':messages,'timeout':timeout,'json_output':json_output,**kwargs},config={'callbacks':[],'tags':[],'metadata':{}})
            if canceled():raise ModelUnavailable('Run canceled; chain reply withheld')
            return answer
        return invoke
    return call

class Provider:
    """Trusted server-injected collector, profile store, lock and local transport.

    collect(model,messages,image) returns live endpoint/config, capacity, slots,
    now and full token/image accounting, not client/model-supplied assertions.
    send must use selected loopback port only and bound output/deadline. Any actual
    send needs these dependencies independently tested before installation.
    """
    def __init__(self,collect,profile_for,lock,send):
        self.collect,self.profile_for,self.lock,self.send=collect,profile_for,lock,send
    def bind(self,role,canceled):
        model=select(role)
        def invoke(messages,timeout=180,json_output=False,*,image=None):
            if not 0<timeout<=180:raise ValueError('Invalid deadline')
            if image and role!='vision':raise ValueError('Images require vision role')
            with self.lock():
                if canceled():raise ModelUnavailable('Run canceled before provider work')
                evidence=self.collect(model,messages,image)
                result=admission(evidence['sample'],self.profile_for(model),now=evidence['now'],selected_role=role,
                    endpoint=evidence['endpoint'],request=evidence['request'],slots=evidence['slots'],canceled=canceled())
                if not result['allowed']:raise ModelUnavailable('Local model admission rejected: '+result['reason'])
                answer=self.send(model,messages,image,timeout,json_output,evidence['request'])
                if canceled():raise ModelUnavailable('Run canceled; provider reply withheld')
                if not isinstance(answer,str) or not answer.strip() or len(answer)>64000:raise ValueError('Incomplete local answer')
                return answer
        return invoke

def langchain_runnable(provider_call):
    """Opt-in integration only after package-access and privacy verification.

    No LangChain memory store or scheduler. Existing durable coordinator owns
    state. Reject ambient tracing/API credentials instead of modifying them.
    """
    forbidden=('LANGCHAIN_TRACING','LANGCHAIN_TRACING_V2','LANGSMITH_TRACING','LANGCHAIN_API_KEY','LANGSMITH_API_KEY')
    if any(os.environ.get(k) for k in forbidden):raise ModelUnavailable('Ambient LangChain/LangSmith tracing or credentials present; integration disabled')
    from langchain_core.runnables import RunnableLambda
    def call(value):
        if any(os.environ.get(k) for k in forbidden):raise ModelUnavailable('Tracing environment changed; integration disabled')
        args={'timeout':value.get('timeout',180),'json_output':value.get('json_output',False)}
        if value.get('image') is not None:args['image']=value['image']
        return provider_call(value['messages'],**args)
    return RunnableLambda(call)
