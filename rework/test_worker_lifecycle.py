import sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent/'deps'))
from unittest.mock import patch
from fastapi.testclient import TestClient
from candidate_api import create_app
with patch('outbox_worker.Worker.once',side_effect=[RuntimeError('simulated transient failure')]+[False]*30):
 app=create_app('unused',{'test':{'projects':[]}},run_worker=True)
 with TestClient(app) as client:
  deadline=time.monotonic()+5;saw_retry=False
  while time.monotonic()<deadline:
   state=client.get('/health').json()['worker'];saw_retry|=state['status']=='retrying'
   if saw_retry and state['status']=='running':break
   time.sleep(.05)
  assert saw_retry and state['status']=='running'
 assert app.state.worker_status['status']=='stopped'
 print('PASS: supervised worker transient-error recovery and clean shutdown')
