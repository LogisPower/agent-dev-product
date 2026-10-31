"""Single resident reasoning endpoint. No loading, external fallback or credentials."""
import json
import urllib.request

HOST = '127.0.0.1'
PORT = 8080
ALIAS = 'bonsai-27b-uncensored'
WEIGHT = 'Ternary-Bonsai-2-27B-PTQ1_0.gguf'
CONTEXT = 32768
MAX_OUTPUT = 1024
REQUEST_SECONDS = 600
CHAT_SECONDS = 720
BASE_URL = f'http://{HOST}:{PORT}'


def verify_backend():
    """Called under the existing inference lock; no inference or model launch."""
    def get(path):
        with urllib.request.urlopen(BASE_URL + path, timeout=5) as response:
            raw = response.read(65537)
        if len(raw) > 65536:
            raise ValueError('Backend metadata exceeds bound')
        return json.loads(raw)
    props = get('/props')
    if props.get('default_generation_settings', {}).get('n_ctx') != CONTEXT:
        raise ValueError('Resident reasoning context does not match configured slot')
    if ALIAS not in [row.get('id') for row in get('/v1/models').get('data', [])]:
        raise ValueError('Resident reasoning alias does not match configured model')
