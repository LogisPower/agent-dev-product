"""Opt-in hosting of original Logis UI. No credentials embedded or scope grants."""
from pathlib import Path
from fastapi import HTTPException
from fastapi.responses import HTMLResponse, FileResponse

def register(app):
    root = Path(__file__).resolve().parents[1]
    assets = {'app.js', 'workspace.js', 'durable-runs.js', 'foundation.js',
              'style.css', 'workspace.css', 'canonical-ui.js', 'canonical-views.js', 'local-work.js'}

    @app.get('/logis', response_class=HTMLResponse)
    def original_logis():
        html = (root / 'chat.html').read_text(encoding='utf-8')
        html = html.replace("window.WORKSPACE_TOKEN='__TOKEN__';", "window.WORKSPACE_TOKEN='';")
        html = html.replace('<script src="/app.js">', '<script src="/logis-assets/canonical-ui.js"></script><script src="/app.js">')
        html = html.replace('</body>', '<script src="/logis-assets/local-work.js"></script><script src="/logis-assets/canonical-views.js"></script></body>')
        for name in assets:
            html = html.replace('"/' + name + '"', '"/logis-assets/' + name + '"')
        return HTMLResponse(html, headers={'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'})

    @app.get('/logis-assets/{name}')
    def original_asset(name: str):
        if name not in assets:
            raise HTTPException(404, 'Asset not found')
        return FileResponse(root / name, headers={'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'})
