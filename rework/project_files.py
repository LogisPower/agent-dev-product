"""Discovery/paging over the existing pinned-handle Windows workspace adapter."""
import base64
import hashlib
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
from workspace_files import Workspace, relative, MAX_BYTES


class ProjectFiles:
    def __init__(self, root, docker_root=None):
        self.workspace = Workspace(root)
        self.root = self.workspace.root
        self.docker_root = str(PurePosixPath(docker_root)) if docker_root else None
        if docker_root and (not self.docker_root.startswith('/') or '..' in PurePosixPath(docker_root).parts):
            raise ValueError('Explicit canonical Docker mount required')

    def relative(self, path):
        # Map only exact server-configured roots; /filename never means /workspace/filename.
        if isinstance(path, str) and PureWindowsPath(path).is_absolute():
            try:
                path = PureWindowsPath(path).relative_to(PureWindowsPath(self.root)).as_posix()
            except ValueError:
                raise ValueError('Windows path is outside this project') from None
        elif isinstance(path, str) and path.startswith('/'):
            if not self.docker_root:
                raise ValueError('No Docker mapping configured for this project')
            try:
                path = PurePosixPath(path).relative_to(self.docker_root).as_posix()
            except ValueError:
                raise ValueError('Docker path is outside this project') from None
        relative(path)
        if any(p.startswith('.') for p in path.split('/')):
            raise ValueError('Hidden/control paths are excluded')
        return path

    def read(self, path, *, offset=0, limit=16384, expected_sha256=None):
        path = self.relative(path)
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 32768:
            raise ValueError('Invalid bounded read page')
        if offset and not expected_sha256:
            raise ValueError('Continuation reads require expected_sha256 from the first page; restart at offset 0')
        try:
            result = self.workspace.read(path)
        except FileNotFoundError:
            return {'status': 'missing', 'path': path, 'next_action': 'List/search this project or wait for the declared creator artifact; do not guess another path.'}
        if expected_sha256 and result['sha256'] != expected_sha256:
            raise ValueError('File changed between pages; restart with the current version')
        text = result.pop('content')
        if offset > len(text):
            raise ValueError('Read offset past end')
        end = min(len(text), offset + limit)
        return {**result, 'status': 'ok', 'content': text[offset:end], 'offset': offset,
                'next_offset': end if end < len(text) else None, 'characters': len(text)}

    def listing(self, directory='', *, cursor=None, limit=100):
        if type(limit) is not int or not 1 <= limit <= 200:
            raise ValueError('Invalid directory page')
        if directory:
            directory = self.relative(directory)
        # Pin the entire ancestor chain during enumeration, excluding junctions and links.
        probe = (directory + '/' if directory else '') + 'logis-list-probe'
        with self.workspace.pinned(probe) as target:
            entries = []
            with os.scandir(target.parent) as scan:
                for scanned,item in enumerate(scan):
                    if scanned >= 5000:
                        raise ValueError('Directory exceeds discovery bound; use a narrower project root')
                    if item.name.startswith('.') or item.name in ('node_modules', '__pycache__'):
                        continue
                    info = item.stat(follow_symlinks=False)
                    if item.is_symlink() or getattr(info, 'st_file_attributes', 0) & 0x400:
                        continue
                    name = (directory + '/' if directory else '') + item.name
                    try:
                        self.relative(name)
                    except ValueError:
                        continue
                    entries.append({'path': name, 'kind': 'directory' if item.is_dir(follow_symlinks=False) else 'file', 'bytes': info.st_size, 'mtime_ns': info.st_mtime_ns})
        entries.sort(key=lambda x: (x['path'].casefold(), x['path']))
        version = hashlib.sha256(json.dumps(entries, sort_keys=True).encode()).hexdigest()
        offset = 0
        if cursor:
            try:
                state = json.loads(base64.urlsafe_b64decode(cursor.encode()))
                if state['version'] != version or state['directory'] != directory:
                    raise ValueError('Directory changed; restart listing')
                offset = state['offset']
                if type(offset) is not int or not 0 <= offset <= len(entries):
                    raise ValueError('Invalid cursor offset')
            except (KeyError, TypeError, json.JSONDecodeError) as error:
                raise ValueError('Invalid directory cursor') from error
        end = offset + limit
        next_cursor = base64.urlsafe_b64encode(json.dumps({'directory': directory, 'version': version, 'offset': end}).encode()).decode() if end < len(entries) else None
        return {'entries': entries[offset:end], 'version': version, 'next_cursor': next_cursor}

    def search(self, query, *, directory='', content=False, cursor=None, limit=50):
        if not isinstance(query, str) or not 1 <= len(query) <= 200 or type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError('Bounded literal query required')
        # One directory per page deliberately avoids unbounded recursive walks.
        page = self.listing(directory, cursor=cursor, limit=100)
        matches, skipped = [], []
        for item in page['entries']:
            if query.casefold() in item['path'].casefold():
                matches.append({**item, 'match': 'filename'})
            elif content and item['kind'] == 'file':
                if item['bytes'] > MAX_BYTES:
                    skipped.append({'path': item['path'], 'reason': 'file exceeds read bound'})
                    continue
                try:
                    data = self.workspace.read(item['path'])
                    pos = data['content'].casefold().find(query.casefold())
                    if pos >= 0:
                        matches.append({'path': item['path'], 'sha256': data['sha256'], 'match': 'content', 'excerpt': data['content'][max(0, pos - 80):pos + 240]})
                except (OSError, ValueError) as error:
                    skipped.append({'path': item['path'], 'reason': type(error).__name__})
        if len(matches) > limit:
            # Never skip unreturned results; require a larger result bound.
            raise ValueError('Too many matches in page; narrow the query or increase limit')
        return {'matches': matches, 'skipped': skipped, 'next_cursor': page['next_cursor'], 'scope': 'one directory; list child directories explicitly'}

    def verify(self, path, sha256):
        value = self.workspace.read(self.relative(path))
        if value['sha256'] != sha256:
            raise ValueError('Committed dependency artifact has changed; no dependent work started')
        return {'path': value['path'], 'sha256': value['sha256'], 'bytes': value['bytes']}

    def write(self, path, content, request_id, expected_sha256=None):
        path = self.relative(path)
        receipt = self.workspace.mutate('edit' if expected_sha256 else 'create', path, content=content,
                                        request_id=request_id, expected_sha256=expected_sha256)
        artifact = self.verify(path, receipt['new_hash'])
        return {'receipt': receipt, 'artifact': artifact}
