"""Pure revision-bound evidence; no storage, model, or network operations."""
import hashlib
import json
import re
from pathlib import PurePosixPath


def _identifier(value, size, label):
    if not isinstance(value, str) or not re.fullmatch('[0-9a-f]{%d}' % size, value):
        raise ValueError('Invalid '+label)
    return value


def _path(value):
    if not isinstance(value,str) or not value or len(value)>240 or '\\' in value or ':' in value:
        raise ValueError('Invalid artifact path')
    parsed=PurePosixPath(value)
    if parsed.is_absolute() or any(p in ('','.','..') for p in value.split('/')):
        raise ValueError('Invalid artifact path')
    return value


def revision(project_id, path, data):
    _identifier(project_id,12,'project ID');_path(path)
    if not isinstance(data,bytes):raise ValueError('Artifact must be exact bytes')
    return dict(project_id=project_id,path=path,sha256=hashlib.sha256(data).hexdigest(),bytes=len(data))


def bind(task, run, artifact, kind, status):
    """References must come from authorized records, never model-provided IDs."""
    _identifier(task.get('id'),16,'task ID');_identifier(run.get('id'),32,'run ID')
    project=_identifier(artifact.get('project_id'),12,'project ID')
    if task.get('project_id')!=project or run.get('project_id')!=project or run.get('task_id')!=task['id']:
        raise ValueError('Task/run/artifact scope mismatch')
    _path(artifact.get('path'))
    _identifier(artifact.get('sha256'),64,'revision hash')
    if type(artifact.get('bytes')) is not int or artifact['bytes']<0:raise ValueError('Invalid byte count')
    if (kind,status) not in {('syntax','passed'),('syntax','failed'),('syntax','unsupported'),('preview_delivery','sent')}:
        raise ValueError('Invalid evidence outcome')
    result=dict(version=1,task_id=task['id'],run_id=run['id'],artifact=dict(artifact),kind=kind,status=status)
    # Identical operation/result does not create duplicate evidence identifiers.
    result['id']=hashlib.sha256(json.dumps(result,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    return result


def assess(evidence, project_id, path, current_bytes):
    current=revision(project_id,path,current_bytes)
    previous=evidence.get('artifact',{})
    if previous.get('project_id')!=project_id or previous.get('path')!=path:
        raise ValueError('Evidence scope mismatch')
    return {'current':current==previous,'evidence_id':evidence['id'],
            'status':evidence['status'] if current==previous else 'stale',
            'kind':evidence['kind']}
