import base64
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from demo import build_demo
from serve import TeamApplication, hash_password


class TeamServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.password = "fixture-password-only"
        cls.password_hash = hash_password(cls.password)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        build_demo(self.temp.name)
        with patch.dict('os.environ', {"VICALL_TEAM_API_TOKEN": ""}):
            self.app = TeamApplication(self.temp.name, {r: {"role": r, **self.password_hash} for r in ("admin", "researcher", "viewer")})

    def tearDown(self):
        self.app.close()
        self.temp.cleanup()

    def request(self, path, method="GET", role=None, payload=None, token=True, origin=None):
        body = json.dumps(payload or {}).encode() if method == "POST" else b""
        env = {"REQUEST_METHOD": method, "PATH_INFO": path, "QUERY_STRING": "", "wsgi.input": io.BytesIO(body),
               "CONTENT_LENGTH": str(len(body)), "CONTENT_TYPE": "application/json", "HTTP_HOST": "localhost:8765"}
        if role:
            env["HTTP_AUTHORIZATION"] = "Basic " + base64.b64encode((role+":"+self.password).encode()).decode()
        if token:
            env["HTTP_X_VICALL_TOKEN"] = self.app.server.token
        if origin:
            env["HTTP_ORIGIN"] = origin
        status = []
        result = b"".join(self.app(env, lambda s,h: status.append(s)))
        return status[0], result

    def test_anonymous_requests_are_rejected(self):
        self.assertTrue(self.request('/api/data')[0].startswith('401'))

    def test_viewer_can_search_but_cannot_modify_research(self):
        status, body = self.request('/api/search', 'POST', 'viewer', {"question": "accounting"})
        self.assertTrue(status.startswith('200'))
        self.assertEqual(json.loads(body)["total"], 3)
        self.assertTrue(self.request('/api/ask', 'POST', 'viewer', {"question": "accounting", "use_ai": False})[0].startswith('200'))
        self.assertTrue(self.request('/api/ask', 'POST', 'viewer', {"question": "accounting", "use_ai": True})[0].startswith('403'))
        self.assertTrue(self.request('/api/workflow', 'POST', 'viewer', {"id": "demo:legal", "notes": "changed"})[0].startswith('403'))

    def test_researcher_cannot_change_automation(self):
        self.assertTrue(self.request('/api/research-settings', 'POST', 'researcher', {"enabled": True})[0].startswith('403'))

    def test_admin_can_change_automation_without_starting_it(self):
        self.assertTrue(self.request('/api/research-settings', 'POST', 'admin', {"enabled": False})[0].startswith('200'))

    def test_browser_writes_require_csrf_token_and_same_origin(self):
        payload = {"id": "demo:legal", "notes": "fixture note"}
        self.assertTrue(self.request('/api/workflow', 'POST', 'researcher', payload, token=False)[0].startswith('403'))
        self.assertTrue(self.request('/api/workflow', 'POST', 'researcher', payload, origin='https://other.example')[0].startswith('403'))
        self.assertTrue(self.request('/api/workflow', 'POST', 'researcher', payload, origin='http://localhost:8765')[0].startswith('200'))

    def test_optimistic_workflow_updates_detect_stale_session(self):
        self.app.workspace.update({"id": "demo:legal", "notes": "first", "expected_updated_at": None})
        with self.assertRaises(ValueError):
            self.app.workspace.update({"id": "demo:legal", "notes": "stale", "expected_updated_at": None})

    def test_api_token_has_researcher_access_and_no_admin_access(self):
        self.app.api_token = "test-token-" + "x"*32
        self.assertEqual(self.app.authenticate("Bearer "+self.app.api_token), ("api-client", "researcher"))


if __name__ == '__main__':
    unittest.main()
