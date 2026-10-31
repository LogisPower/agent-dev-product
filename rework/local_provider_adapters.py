"""Existing-provider composition with an explicit, never-created shared lock file."""
import json,os,threading,time,urllib.request
from contextlib import contextmanager
from pathlib import Path
from activation_entrypoint import RuntimeAdapters
from local_dsh_transport import DshTransport
from workspace_files import Workspace

@contextmanager
def existing_slot(path):
    from inference_gate import _try_lock,_unlock,InferenceBusyError
    path=Path(path)
    if not path.is_absolute() or '..' in path.parts:raise ValueError('Explicit existing shared inference lock required')
    with Workspace(path.parent).pinned(path.name):
        before=path.lstat()
        if path.is_symlink() or getattr(path,'is_junction',lambda:False)() or before.st_nlink!=1 or before.st_size<1:raise ValueError('Unshared existing regular lock required')
        # r+b cannot create the lock or parent directory.
        with path.open('r+b') as handle:
            opened=os.fstat(handle.fileno())
            if (before.st_dev,before.st_ino)!=(opened.st_dev,opened.st_ino) or opened.st_nlink!=1 or opened.st_size<1:raise ValueError('Inference lock changed while opening')
            if not _try_lock(handle):raise InferenceBusyError('Existing shared inference slot is busy')
            try:yield
            finally:_unlock(handle)


def resident_idle():
    from local_model_config import verify_backend,BASE_URL
    from inference_gate import InferenceBusyError
    verify_backend()
    with urllib.request.urlopen(BASE_URL+'/slots',timeout=5) as response:raw=response.read(65537)
    if len(raw)>65536:raise ValueError('Resident slot response exceeds bound')
    slots=json.loads(raw)
    if not isinstance(slots,list) or not slots or any(not isinstance(slot,dict) or slot.get('is_processing') is not False for slot in slots):raise InferenceBusyError('Resident model is busy or slot state is unverified')

class CoordinatedDshTransport(DshTransport):
    def __init__(self,rpc,cwd,project,lock_path,probe=resident_idle):
        super().__init__(rpc,cwd,project);self.lock_path=Path(lock_path);self.probe=probe;self.leases={};self.pending=set();self.mutex=threading.Lock()
    def release(self,request):
        with self.mutex:lease=self.leases.pop(request,None)
        if lease is not None:lease.__exit__(None,None,None)
    def acquire(self,request):
        from inference_gate import InferenceBusyError
        lease=existing_slot(self.lock_path)
        with self.mutex:
            if self.leases:raise InferenceBusyError('A local handoff already holds this provider adapter')
            lease.__enter__();self.leases[request]=lease
    def prepare(self,request,attempt,*,timeout,stopping):
        from inference_gate import InferenceBusyError
        self.session(request)
        if type(timeout) not in (int,float) or not 0<timeout<=120:raise ValueError('Admission wait must be bounded to 120 seconds')
        deadline=time.monotonic()+timeout
        with self.mutex:self.pending.add(request)
        attempt.checkpoint({'phase':'waiting_for_provider','request_id':request,'submitted':False})
        while True:
            attempt.check()
            if stopping():raise RuntimeError('Local worker stopping before submission')
            try:
                self.acquire(request);self.probe();attempt.check()
                if stopping():raise RuntimeError('Local worker stopping before submission')
                attempt.checkpoint({'phase':'provider_ready','request_id':request,'submitted':False});return
            except InferenceBusyError:
                self.release(request)
                if time.monotonic()>=deadline:raise TimeoutError('Provider admission deadline; no DSH request submitted')
                attempt.cancelled.wait(min(0.25,max(0,deadline-time.monotonic())))
            except BaseException:self.release(request);raise
    def submit(self,request,packet):
        with self.mutex:prepared=request in self.pending and request in self.leases
        if not prepared:self.acquire(request)
        try:
            if not prepared:self.probe()
            with self.mutex:self.pending.discard(request)
            return super().submit(request,packet)
        except BaseException:self.release(request);raise
    def poll(self,request):
        try:
            value=super().poll(request)
            if value['status'] in ('completed','failed','canceled'):self.release(request)
            return value
        except BaseException:
            # Keep admission locked until caller requests cancellation/reconciliation.
            raise
    def cancel(self,request):
        with self.mutex:unsubmitted=request in self.pending;self.pending.discard(request)
        try:
            if not unsubmitted:return super().cancel(request)
        finally:self.release(request)


def make_existing_adapters(binding,shared_lock,rpc=None):
    lock=Path(shared_lock)
    if not lock.is_absolute() or lock.is_relative_to(binding.root):raise ValueError('Shared provider lock must be explicit and outside project files')
    if not lock.is_file():raise ValueError('Existing shared lock is missing; it will not be created')
    def text(messages,timeout=600,json_output=False):
        from chat_transport import completion
        from provider_cancel import current,ProviderCanceled
        if current.get()():raise ProviderCanceled('Canceled before existing-provider admission')
        with existing_slot(lock):
            resident_idle();return completion(messages,timeout=timeout,json_output=json_output)
    def build(messages):return text(messages,timeout=180,json_output=True)
    from canonical_context import provider_tokens
    transport=CoordinatedDshTransport(rpc,binding.container_root,binding.project,lock) if rpc is not None else None
    return RuntimeAdapters(request_chat=text,request_build=build,context_counter=provider_tokens,
        local_transport=transport,local_planner=text if transport is not None else None)
