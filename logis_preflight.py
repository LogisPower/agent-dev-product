"""Read-only Logis readiness checks. Does not import the application or start services."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import urllib.request


def probe(url, expected=None, workspace=False):
    try:
        with urllib.request.urlopen(url, timeout=2) as response:
            value = json.load(response)
        if not isinstance(value, dict):
            return {'reachable': True, 'ready': False, 'reason': 'Unexpected health response'}
        if workspace:
            identified = 'model' in value and 'context' in value
            return {'reachable': True, 'ready': identified and value.get('model') != 'offline',
                    'reason': 'model_offline' if identified and value.get('model') == 'offline' else
                    ('workspace_response' if identified else 'unrecognized_service')}
        if expected and value.get('status') != expected:
            return {'reachable': True, 'ready': False, 'reason': 'Unexpected health response'}
        return {'reachable': True, 'ready': True}
    except Exception as error:
        return {'ready': False, 'reason': type(error).__name__}


def dependency_check(root):
    dependency_root = root / 'runtime' / 'agent-libs'
    required = dependency_root / 'langgraph' / 'graph' / '__init__.py'
    try:
        with required.open('rb') as stream:
            stream.read(1)
    except PermissionError:
        return {'ready': False, 'reason': 'access_denied',
                'action': 'Run Logis under the Windows account that installed it. Do not reinstall or change permissions automatically.'}
    except FileNotFoundError:
        return {'ready': False, 'reason': 'missing_dependency',
                'action': 'Review the existing dependency installation before authorizing any installation.'}
    except OSError as error:
        return {'ready': False, 'reason': type(error).__name__}
    code = ('import sys,site; site.addsitedir(sys.argv[1]); '
            'sys.path.insert(0,sys.argv[1]); '
            'import langgraph.graph,langgraph.checkpoint.sqlite,qdrant_client')
    try:
        result = subprocess.run([sys.executable, '-B', '-c', code, str(dependency_root)],
                                capture_output=True, timeout=20)
        return {'ready': result.returncode == 0,
                'reason': 'available' if result.returncode == 0 else 'dependency_import_failed'}
    except subprocess.TimeoutExpired:
        return {'ready': False, 'reason': 'dependency_check_timeout'}
    except OSError as error:
        return {'ready': False, 'reason': type(error).__name__}


def report(root):
    return {'service': 'logis-preflight', 'dependencies': dependency_check(root),
            'services': {
                'workspace': probe('http://127.0.0.1:8090/api/health', workspace=True),
                'model_27b': probe('http://127.0.0.1:8081/health', 'ok'),
                'model_9b_optional': probe('http://127.0.0.1:8082/health', 'ok'),
                'embedding_api': probe('http://127.0.0.1:1234/v1/models')},
            'limits': ['API reachability does not verify model responses or embeddings.',
                       'Mind Vault candidate integration is not verified.',
                       'No services started, models loaded, inference requests submitted, or application data changed.']}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument('--dependencies-only', action='store_true')
    args = parser.parse_args()
    result = dependency_check(args.root) if args.dependencies_only else report(args.root)
    print(json.dumps(result, indent=2))
    sys.exit(0 if (result if args.dependencies_only else result['dependencies'])['ready'] else 2)
