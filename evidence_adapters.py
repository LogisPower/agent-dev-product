"""Staged explicit adapters. Callers authorize references before invocation."""
import json
from artifact_evidence import revision,bind


def check_bytes(task,run,path,data,javascript_check=None):
    """Check the captured bytes, not a mutable original path.

    An optional JS runner receives exact bytes and must check a private snapshot.
    No JS runner means unsupported, never passed. This adapter installs nothing.
    """
    if not isinstance(data,bytes) or len(data)>120000:
        raise ValueError('Check source must be bytes within 120 KB')
    artifact=revision(run['project_id'],path,data)
    bind(task,run,artifact,'syntax','unsupported')  # Validate scope before any checker.
    suffix=path.rsplit('.',1)[-1] if '.' in path else ''
    status='unsupported'
    if suffix in ('py','json','js','mjs','cjs'):
        if suffix in ('js','mjs','cjs') and javascript_check is None:
            pass
        else:
            try:
                if suffix=='py':compile(data.decode('utf-8'),path,'exec')
                elif suffix=='json':json.loads(data.decode('utf-8'))
                else:
                    outcome=javascript_check(data,suffix)
                    if type(outcome) is not bool:raise ValueError('Invalid checker response')
                    status='passed' if outcome else 'failed'
                if suffix in ('py','json'):status='passed'
            except (SyntaxError,ValueError,UnicodeError):status='failed'
    return bind(task,run,artifact,'syntax',status)


def deliver_preview(task,run,path,data,send_bytes):
    """Return evidence only after the sender reports all bytes sent.

    This proves delivery to a transport, not successful browser rendering.
    Exceptions/short writes produce no successful evidence and are never retried.
    """
    if len(data)>5_000_000:raise ValueError('Preview file too large')
    evidence=bind(task,run,revision(run['project_id'],path,data),'preview_delivery','sent')
    written=send_bytes(data)
    if type(written) is not int or written!=len(data):raise OSError('Preview delivery outcome uncertain')
    return evidence
