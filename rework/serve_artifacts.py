"""Separate-origin local preview. No app token, filesystem traversal or network access."""
import sys,re,hashlib,json
from pathlib import Path
ROOT=Path(__file__).parent;sys.path.insert(0,str(ROOT/'deps'))
from fastapi import FastAPI,HTTPException
from fastapi.responses import Response
from candidate_build import artifact
import uvicorn
app=FastAPI(docs_url=None,redoc_url=None,openapi_url=None)
@app.get('/health')
def health():return {'service':'logis-rework-artifacts'}
@app.get('/artifacts/{run}')
def preview(run:str):
    if not re.fullmatch('[a-f0-9]{32}',run):raise HTTPException(404)
    path=artifact(run)
    if not path.is_file() or path.stat().st_size>18000:raise HTTPException(404)
    raw=path.read_bytes()
    receipt=json.loads((path.parent/'receipt.json').read_text())
    if hashlib.sha256(raw).hexdigest()!=receipt['sha256'] or len(raw)!=receipt['bytes']:raise HTTPException(409,'Artifact differs from checked bytes')
    return Response(raw,media_type='text/html',headers={'Content-Security-Policy':"sandbox allow-scripts; default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; connect-src 'none'; form-action 'none'; base-uri 'none'; frame-ancestors 'none'",'X-Content-Type-Options':'nosniff','Referrer-Policy':'no-referrer','Cache-Control':'no-store','ETag':'"'+hashlib.sha256(raw).hexdigest()+'"'})
if __name__=='__main__':uvicorn.run(app,host='127.0.0.1',port=8093)
