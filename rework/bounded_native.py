"""Bounded pipe buffers for fixed native commands, never arbitrary user commands."""
import subprocess,threading,time,types
class OutputLimit(ValueError):pass
class CleanupFailed(OSError):pass

def run_bounded(args,*,timeout=8,creationflags=0,capture_output=True,popen=subprocess.Popen):
    proc=popen(args,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,creationflags=creationflags,bufsize=0)
    stop=threading.Event();overflow=threading.Event();failed=threading.Event();buffers=[bytearray(),bytearray()]
    def read(pipe,index,limit):
        try:
            while not stop.is_set():
                chunk=pipe.read(256)
                if not chunk:break
                room=limit-len(buffers[index])
                buffers[index].extend(chunk[:max(0,room)])
                if len(chunk)>room:overflow.set();break
        except (OSError,ValueError):failed.set()
    threads=[threading.Thread(target=read,args=(proc.stdout,0,4096),daemon=True),threading.Thread(target=read,args=(proc.stderr,1,1024),daemon=True)]
    for thread in threads:thread.start()
    deadline=time.monotonic()+timeout;problem=None
    try:
        while True:
            if overflow.is_set():problem=OutputLimit('native_output_budget');break
            if failed.is_set():problem=OSError('native_pipe_failed');break
            if proc.poll() is not None and not any(t.is_alive() for t in threads):break
            if time.monotonic()>=deadline:problem=subprocess.TimeoutExpired('fixed-native-query',timeout);break
            stop.wait(0.01)
    finally:
        stop.set()
        if proc.poll() is None:proc.kill()
        try:proc.wait(timeout=1)
        except subprocess.TimeoutExpired:raise CleanupFailed('owned_native_process_not_reaped')
        for thread in threads:thread.join(timeout=1)
        # Fixed scripts do not spawn descendants. Do not kill unrelated trees.
        if any(t.is_alive() for t in threads):raise CleanupFailed('owned_native_pipe_not_closed')
        proc.stdout.close();proc.stderr.close()
    if problem:raise problem
    return types.SimpleNamespace(returncode=proc.returncode,stdout=bytes(buffers[0]),stderr=b'')
