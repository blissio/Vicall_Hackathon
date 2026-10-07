import json
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from app import AppAlreadyRunning, Workspace, make_server
from collect_osm import export
from datetime import datetime, timezone


def fixture(directory):
    export({"collected_at": "2026-10-06T00:00:00Z", "payload": {"elements": [
        {"type": "node", "id": 1, "lat": 40.44, "lon": -79.99,
         "tags": {"name": "Test Cafe", "amenity": "cafe", "email": "info@example.com"}},
        {"type": "node", "id": 2, "lat": 40.45, "lon": -79.98,
         "tags": {"name": "Second Cafe", "amenity": "cafe"}}
    ]}}, directory)


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.directory = Path(self.temporary.name)
        fixture(self.directory)
        self.workspace = Workspace(self.directory)

    def tearDown(self):
        self.temporary.cleanup()

    def test_research_survives_reload_and_patches_do_not_erase_notes(self):
        self.workspace.update({"id": "osm:node:1", "notes": "Evidence with a source URL", "stage": "Researching"})
        self.workspace.update({"id": "osm:node:1", "shortlisted": True})
        restarted = Workspace(self.directory)
        workflow = restarted.data()["businesses"][0]["workflow"]
        self.assertEqual(workflow["notes"], "Evidence with a source URL")
        self.assertEqual(workflow["stage"], "Researching")
        self.assertTrue(workflow["shortlisted"])

    def test_invalid_changes_do_not_save(self):
        for patch_value in ({"stage": "invented"}, {"shortlisted": "yes"}, {"notes": "x" * 12001}):
            with self.assertRaises(ValueError):
                self.workspace.update({"id": "osm:node:1", **patch_value})
        with self.assertRaises(KeyError):
            self.workspace.update({"id": "missing", "notes": "test"})
        self.assertFalse(self.workspace.workflow_file.exists())

    def test_neighborhoods_enrich_old_snapshots_and_export_with_research(self):
        dataset = self.directory / "processed/businesses.jsonl"
        rows = [json.loads(line) for line in dataset.read_text(encoding="utf-8").splitlines()]
        for row in rows:
            for key in ("neighborhood", "neighborhood_method", "neighborhood_candidates"):
                row.pop(key, None)
        rows[0]["location"]["coordinates"] = [-79.9510172, 40.4828447]
        dataset.write_text("".join(json.dumps(row)+"\n" for row in rows), encoding="utf-8")
        original = dataset.read_bytes()
        self.workspace.update({"id": "osm:node:1", "notes": "Keep neighborhood research"})
        restarted = Workspace(self.directory)
        cafe = restarted.by_id["osm:node:1"]
        self.assertEqual(cafe["neighborhood"], "Upper Lawrenceville")
        self.assertEqual(cafe["neighborhood_method"], "mapped_point")
        self.assertEqual(dataset.read_bytes(), original)
        import csv
        import io
        exported = list(csv.DictReader(io.StringIO(restarted.export_csv(["osm:node:1"]).decode("utf-8-sig"))))
        self.assertEqual(exported[0]["neighborhood"], cafe["neighborhood"])
        self.assertEqual(exported[0]["notes"], "Keep neighborhood research")
        self.assertIn("pittsburghpa.gov", exported[0]["neighborhood_source"])

    def test_export_is_scoped_and_includes_safe_notes_and_attribution(self):
        self.workspace.update({"id": "osm:node:1", "notes": " =HYPERLINK(1)"})
        text = self.workspace.export_csv(["osm:node:1", "osm:node:1"]).decode("utf-8-sig")
        self.assertIn("Test Cafe", text)
        self.assertNotIn("Second Cafe", text)
        self.assertIn("' =HYPERLINK(1)", text)
        self.assertIn("OpenStreetMap contributors", text)

    def test_failed_collection_preserves_dataset_and_notes(self):
        self.workspace.update({"id": "osm:node:1", "notes": "Preserve me"})
        before = (self.directory / "processed/businesses.jsonl").read_bytes()
        with patch("app.subprocess.run", return_value=subprocess.CompletedProcess([], 1, "", "Network unavailable")):
            self.workspace._run_job("refresh")
        self.assertEqual(self.workspace.job_status()["status"], "failed")
        self.assertEqual(before, (self.directory / "processed/businesses.jsonl").read_bytes())
        self.assertEqual(self.workspace.workflow["osm:node:1"]["notes"], "Preserve me")

    def test_rebuild_job_publishes_complete_snapshot_and_keeps_research(self):
        self.workspace.update({"id": "osm:node:1", "notes": "Keep", "shortlisted": True})
        self.workspace._run_job("clean")
        self.assertEqual(self.workspace.job_status()["status"], "complete")
        self.assertEqual(len(self.workspace.rows), 2)
        self.assertEqual(self.workspace.workflow["osm:node:1"]["notes"], "Keep")
        self.assertTrue(list((self.directory / "snapshots").iterdir()))

    def test_corrupt_dataset_keeps_last_loaded_directory(self):
        (self.directory / "processed/businesses.jsonl").write_text("broken json", encoding="utf-8")
        self.workspace.reload()
        self.assertEqual(len(self.workspace.rows), 2)
        self.assertIn("Could not load", self.workspace.load_error)

    def test_bad_workflow_file_is_not_silently_overwritten(self):
        self.workspace.workflow_file.write_text("not JSON", encoding="utf-8")
        with self.assertRaises(ValueError):
            Workspace(self.directory)
        self.assertEqual(self.workspace.workflow_file.read_text(encoding="utf-8"), "not JSON")

    def run_saved_audit(self, score=70):
        result = {"requested_url": "https://example.com/", "final_url": "https://example.com/", "reachability": "reachable",
                  "score": score, "grade": "review", "http_status": 200, "audit_version": "1.0",
                  "checked_at": datetime.now(timezone.utc).isoformat(), "message": "HTML returned", "checks": [],
                  "recommendations": [{"recommendation": "Add a useful description"}]}
        self.workspace.audit_job = {"status": "running", "completed": 0, "total": 1, "results": []}
        with patch("app.audit_website", return_value=result), patch.object(self.workspace.audit_cancel, "wait", return_value=False):
            self.workspace._run_audits([{"id": "osm:node:1", "url": "https://example.com/", "name": "Test Cafe", "target_source": "user_supplied"}])

    def test_audit_persistence_history_and_exports_keep_research(self):
        self.workspace.update({"id": "osm:node:1", "notes": "Keep my notes"})
        for score in (50,60,70,80,90,95):
            self.run_saved_audit(score)
        restarted = Workspace(self.directory)
        report = restarted.audit_report("osm:node:1")
        self.assertEqual(report["latest"]["score"],95)
        self.assertEqual(len(report["history"]),4)
        self.assertEqual(report["latest"]["identity_status"],"unverified")
        self.assertEqual(restarted.data()["businesses"][0]["audit"]["score"],95)
        text = restarted.export_csv(["osm:node:1"]).decode("utf-8-sig")
        self.assertIn("Add a useful description",text)
        self.assertIn("Keep my notes",text)

    def test_fresh_audit_cache_and_batch_validation(self):
        self.run_saved_audit()
        result = self.workspace.start_audits({"ids": ["osm:node:1"]})
        self.assertEqual(result["status"],"complete")
        self.assertEqual(result["skipped"],1)
        for payload in ({"ids":[]},{"ids":["osm:node:1"]*26},{"ids":["osm:node:1"],"url":"http://127.0.0.1/"}):
            with self.assertRaises(ValueError):
                self.workspace.start_audits(payload)

    def test_cancellation_keeps_completed_results(self):
        self.run_saved_audit()
        self.workspace.audit_job["status"]="running"
        self.workspace.cancel_audits()
        self.workspace._run_audits([{"id":"osm:node:2","name":"Second Cafe","url":"https://example.com/"}])
        self.assertEqual(self.workspace.audit_job["status"],"cancelled")
        self.assertEqual(self.workspace.audit_report("osm:node:1")["latest"]["score"],70)
        self.assertIsNone(self.workspace.audit_report("osm:node:2")["latest"])


class LocalServerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.directory = Path(self.temporary.name)
        fixture(self.directory)
        self.server = make_server(self.directory, 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temporary.cleanup()

    def request(self, path, payload=None, token=True, origin=None):
        headers = {"X-Vicall-Token": self.server.token} if token else {}
        if origin:
            headers["Origin"] = origin
        data = None
        if payload is not None:
            data = json.dumps(payload).encode()
            headers["Content-Type"] = "application/json"
        return urlopen(Request(self.url + path, data=data, headers=headers), timeout=10)

    def test_api_requires_local_token_and_rejects_foreign_origin(self):
        for kwargs in ({"token": False}, {"origin": "https://example.com"}):
            with self.assertRaises(HTTPError) as context:
                self.request("/api/data", **kwargs)
            self.assertEqual(context.exception.code, 403)
        with self.request("/api/data") as response:
            self.assertEqual(json.load(response)["summary"]["total"], 2)

    def test_ui_and_workflow_endpoints(self):
        with self.request("/", token=False) as response:
            self.assertIn(self.server.token, response.read().decode())
            self.assertIn("frame-ancestors 'none'", response.headers["Content-Security-Policy"])
        with self.request("/api/workflow", {"id": "osm:node:1", "shortlisted": True}) as response:
            self.assertTrue(json.load(response)["shortlisted"])
        with self.request("/api/export", {"ids": ["osm:node:1"]}) as response:
            self.assertIn("attachment", response.headers["Content-Disposition"])
            self.assertIn("Test Cafe", response.read().decode("utf-8-sig"))

    def test_files_outside_ui_are_not_served(self):
        with self.assertRaises(HTTPError) as context:
            self.request("/data/workspace.json")
        self.assertEqual(context.exception.code, 404)

    def test_second_app_cannot_overwrite_same_workspace(self):
        with self.assertRaises(AppAlreadyRunning) as context:
            make_server(self.directory, 0)
        self.assertEqual(context.exception.url, self.url)

    def test_audit_report_and_validation_endpoints(self):
        with self.request("/api/audit-report?id=osm%3Anode%3A1") as response:
            self.assertIsNone(json.load(response)["latest"])
        with self.request("/api/audit-job") as response:
            self.assertEqual(json.load(response)["status"],"idle")
        with self.request("/audit-ui.js",token=False) as response:
            self.assertIn("window.vicallAudit",response.read().decode())
        with self.assertRaises(HTTPError) as context:
            self.request("/api/audit",{"ids":["osm:node:1"],"url":"http://localhost/"})
        self.assertEqual(context.exception.code,400)


if __name__ == "__main__":
    unittest.main()
