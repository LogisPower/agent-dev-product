"""Bounded latest-run visibility. No job resumption or tool execution."""
import json
import os
from pathlib import Path
import re
import tempfile
import task_binding

LIMIT = 65536
FIELDS = ('id', 'status', 'phase', 'action', 'mode', 'model', 'started',
          'finished', 'finalized', 'context_tokens', 'graph', 'error', 'task_binding')
TEXT_LIMITS = {'id': 32, 'status': 32, 'phase': 64, 'action': 64, 'mode': 64,
               'model': 128, 'started': 64, 'finished': 64, 'error': 4096}


def _validated(value):
    if not isinstance(value, dict) or value.get('status') not in ('running', 'done', 'error', 'stopped'):
        raise ValueError('Invalid run record')
    record = {key: value[key] for key in FIELDS if key in value}
    for key, limit in TEXT_LIMITS.items():
        if key in record and (not isinstance(record[key], str) or len(record[key]) > limit):
            raise ValueError('Invalid run text field')
    if not re.fullmatch('[a-f0-9]{32}', record.get('id', '')):
        raise ValueError('Invalid run identity')
    if 'finalized' in record and type(record['finalized']) is not bool:
        raise ValueError('Invalid finalization flag')
    if 'context_tokens' in record and (type(record['context_tokens']) is not int or record['context_tokens'] < 0):
        raise ValueError('Invalid token count')
    if 'graph' in record and not isinstance(record['graph'], dict):
        raise ValueError('Invalid graph metadata')
    if 'task_binding' in record:
        record['task_binding']=task_binding.validate(record['task_binding'])
        if record['task_binding']['run_id']!=record['id']:raise ValueError('Run/task binding mismatch')
    events = value.get('events', [])
    if not isinstance(events, list) or len(events) > 50:
        raise ValueError('Invalid events')
    record['events'] = []
    for event in events:
        if not isinstance(event, dict) or any(not isinstance(event.get(key), str) or len(event[key]) > limit for key, limit in (('time', 64), ('text', 800))):
            raise ValueError('Invalid event')
        record['events'].append({'time': event['time'], 'text': event['text']})
    return record


def save(folder, job):
    folder = Path(folder)
    target = folder / 'run-progress.json'
    if target.is_symlink():
        raise ValueError('Unsafe run record path')
    record = {key: job[key] for key in FIELDS if key in job}
    record['events'] = [{'time': str(e.get('time', ''))[:64],
                         'text': str(e.get('text', ''))[:800]}
                        for e in job.get('events', [])[-50:]]
    record = _validated(record)
    encoded = json.dumps(record, ensure_ascii=False, allow_nan=False).encode('utf-8')
    # Keep the newest events within the byte budget, including multilingual text.
    while len(encoded) > LIMIT and record['events']:
        record['events'].pop(0)
        encoded = json.dumps(record, ensure_ascii=False, allow_nan=False).encode('utf-8')
    if len(encoded) > LIMIT:
        raise ValueError('Run record exceeds size limit')
    name = None
    try:
        with tempfile.NamedTemporaryFile(dir=folder, prefix='.run-', suffix='.tmp', delete=False) as stream:
            name = stream.name
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, target)
    finally:
        if name and os.path.exists(name):
            os.unlink(name)


def restore(folder):
    """Only used when no in-process job exists. Never marks old work running."""
    path = Path(folder) / 'run-progress.json'
    try:
        if path.is_symlink():
            raise ValueError('Unsafe run record path')
        with path.open('rb') as stream:
            raw = stream.read(LIMIT + 1)
        if len(raw) > LIMIT:
            raise ValueError('Oversized run record')
        record = _validated(json.loads(raw))
        record['recovered'] = True
        if record['status'] == 'running' or not record.get('finalized'):
            record['last_saved_phase'] = record.get('phase')
            record.update(status='interrupted', phase='interrupted', finalized=True,
                          error='The previous run did not finish before the workspace stopped. Review saved files and tool records before starting another run. Nothing was resumed automatically.')
            record['events'] = record.get('events', [])[-49:] + [{'time': '', 'text': record['error']}]
        return record
    except FileNotFoundError:
        return None
    except (OSError, ValueError, TypeError, RecursionError):
        return {'status': 'error', 'phase': 'record_unavailable', 'finalized': True,
                'error': 'Previous run record is unreadable or invalid. Inspect saved files before retrying.', 'events': []}
