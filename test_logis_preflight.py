import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import logis_preflight as app


class ReadinessTests(unittest.TestCase):
    def test_denial_is_not_reported_as_missing(self):
        with patch.object(Path, 'open', side_effect=PermissionError), patch.object(app.subprocess, 'run') as run:
            self.assertEqual(app.dependency_check(Path('test'))['reason'], 'access_denied')
            run.assert_not_called()

    def test_missing_dependency_does_not_install(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(app.subprocess, 'run') as run:
            self.assertEqual(app.dependency_check(Path(directory))['reason'], 'missing_dependency')
            run.assert_not_called()

    def test_model_loading_is_not_ready(self):
        with patch.object(app.urllib.request, 'urlopen', return_value=io.BytesIO(b'{"status":"loading"}')):
            self.assertFalse(app.probe('http://127.0.0.1/health', 'ok')['ready'])

    def test_health_ok(self):
        with patch.object(app.urllib.request, 'urlopen', return_value=io.BytesIO(b'{"status":"ok"}')):
            self.assertTrue(app.probe('http://127.0.0.1/health', 'ok')['ready'])

    def test_connection_failure_is_not_ready(self):
        with patch.object(app.urllib.request, 'urlopen', side_effect=ConnectionError):
            self.assertFalse(app.probe('http://127.0.0.1/health')['ready'])

    def test_workspace_offline_is_reachable_not_ready(self):
        with patch.object(app.urllib.request, 'urlopen', return_value=io.BytesIO(b'{"model":"offline","context":null}')):
            result = app.probe('http://127.0.0.1/api/health', workspace=True)
            self.assertTrue(result['reachable'])
            self.assertFalse(result['ready'])

    def test_foreign_json_service_is_not_workspace(self):
        with patch.object(app.urllib.request, 'urlopen', return_value=io.BytesIO(b'{"status":"ok"}')):
            self.assertEqual(app.probe('http://127.0.0.1/api/health', workspace=True)['reason'], 'unrecognized_service')

    def test_dependency_child_access_failure(self):
        with patch.object(Path, 'open', return_value=io.BytesIO(b'x')), patch.object(app.subprocess, 'run', side_effect=PermissionError):
            self.assertFalse(app.dependency_check(Path('test'))['ready'])


if __name__ == '__main__':
    unittest.main()
