import csv
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import Workspace
from demo import build_demo
from evaluate import CASES, evaluate
from intelligence import validate_answer, generate_answer
from storage import backup, connect, load_document, save_document, stamp


class IntelligenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.directory = Path(self.temp.name)
        self.workspace = build_demo(self.directory)

    def tearDown(self):
        self.temp.cleanup()

    def test_issue_filter_does_not_turn_blocked_checks_into_bad_websites(self):
        answer = self.workspace.search_businesses({"question": "accounting", "require_website_issue": True})
        self.assertEqual([r["id"] for r in answer["results"]], ["demo:accounting-issues"])
        self.assertEqual(answer["metrics"]["external_page_requests"], 0)

    def test_district_is_distinct_from_school_and_parent_survives_restart(self):
        restarted = Workspace(self.directory)
        results = restarted.search_businesses({"organization_type": "school_district"})["results"]
        self.assertEqual([r["id"] for r in results], ["demo:district"])
        self.assertEqual(restarted.intelligence_detail("demo:school")["review"]["parent_id"], "demo:district")

    def test_role_requires_supporting_source_and_date(self):
        payload = {"business_id": "demo:legal", "name": "Person", "role": "Partner", "source_url": "https://example.com/team"}
        with self.assertRaises(ValueError):
            self.workspace.save_person(payload)
        with self.assertRaises(ValueError):
            self.workspace.save_person({**payload, "excerpt": "Public partner role", "observed_at": "2099-01-01"})

    def test_parent_relationship_cannot_create_cycle(self):
        with self.assertRaises(ValueError):
            self.workspace.save_organization({"id": "demo:district", "organization_type": "school_district", "parent_id": "demo:school", "source_url": "https://example.com/", "excerpt": "District", "observed_at": stamp()})

    def test_saved_search_and_answer_history_survive_restart(self):
        search = self.workspace.save_search({"name": "Legal providers", "query": {"question": "legal", "intent": "providers"}})
        self.workspace.answer_question(search["query"])
        status = Workspace(self.directory).intelligence_status()
        self.assertEqual(status["saved_searches"][0]["name"], "Legal providers")
        self.assertEqual(len(status["history"]), 1)
        self.workspace.delete_search({"id": search["id"]})
        self.assertEqual(self.workspace.intelligence_status()["saved_searches"], [])

    def test_ai_cannot_cite_evidence_from_a_different_business(self):
        context = [{"business_id": "a", "evidence": [{"id": "ea"}]}, {"business_id": "b", "evidence": [{"id": "eb"}]}]
        with self.assertRaises(ValueError):
            validate_answer({"recommendations": [{"business_id": "a", "evidence_ids": ["eb"], "interpretation": "Wrong"}], "unknowns": []}, context)

    def test_invalid_ai_response_falls_back_to_evidence_without_publishing_it(self):
        def provider(question, context):
            return {"recommendations": [{"business_id": "invented", "evidence_ids": ["bad"], "interpretation": "Wrong"}], "unknowns": []}, {}
        answer = self.workspace.answer_question({"question": "accounting", "use_ai": True}, provider=provider)
        self.assertIsNone(answer["ai"])
        self.assertTrue(answer["ai_error"])
        self.assertTrue(answer["results"])

    def test_valid_ai_citations_are_resolved_by_server(self):
        def provider(question, context):
            row = context[0]
            return {"recommendations": [{"business_id": row["business_id"], "evidence_ids": [row["evidence"][0]["id"]], "interpretation": "Consider reviewing this organization"}], "unknowns": ["Budget unknown"]}, {"input_tokens": 100, "output_tokens": 30}
        answer = self.workspace.answer_question({"question": "legal", "use_ai": True}, provider=provider)
        self.assertEqual(answer["mode"], "ai_with_evidence")
        self.assertTrue(answer["ai"]["recommendations"][0]["citations"][0]["source_url"])

    def test_export_uses_correct_source_attribution_and_includes_roles(self):
        content = self.workspace.export_csv(["demo:district"]).decode("utf-8-sig")
        row = next(csv.DictReader(io.StringIO(content)))
        self.assertEqual(row["organization_type"], "school_district")
        self.assertIn("Communications director", row["people_evidence_json"])
        self.assertNotIn("OpenStreetMap", row["attribution"])

    def test_query_validation_rejects_malformed_fields(self):
        for value in ({"limit": True}, {"limit": 500}, {"require_contact": "false"}, {"segment": "imaginary"}, {"question": ["test"]}):
            with self.assertRaises(ValueError):
                self.workspace.search_businesses(value)

    def test_sqlite_remains_authoritative_if_legacy_export_is_changed(self):
        path = self.directory / "workspace.json"
        save_document(path, {"saved": "evidence"})
        path.write_text('{"saved":"accidentally changed export"}', encoding="utf-8")
        self.assertEqual(load_document(path)["saved"], "evidence")

    def test_sqlite_backup_contains_reviews_contacts_and_answers(self):
        self.workspace.answer_question({"question": "accounting"})
        destination = self.directory / "backup.sqlite3"
        backup(self.directory, destination)
        import sqlite3
        from contextlib import closing
        with closing(sqlite3.connect(destination)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM contacts").fetchone()[0], 2)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM answers").fetchone()[0], 1)

    def test_research_resume_only_requeues_unfinished_tasks(self):
        self.workspace.research_job.update(status="interrupted", pending_ids=["demo:legal"], pending_sources=[])
        with patch.object(self.workspace, "start_research", return_value={"status": "running"}) as start:
            self.workspace.resume_research()
            start.assert_called_once_with({"ids": ["demo:legal"], "sources": [], "force": True})

    def test_synthetic_evaluation_matches_expected_sets(self):
        result = evaluate(self.workspace, CASES)
        self.assertEqual(result["exact_set_matches"], result["case_count"])

    def test_starter_catalog_deduplicates_and_keeps_suburbs_explicit(self):
        first = self.workspace.import_target_catalog()
        second = self.workspace.import_target_catalog()
        self.assertEqual(first["added"], 5)
        self.assertEqual(second["added"], 0)
        self.assertTrue(any("outside" in c.get("service_area", "") for c in self.workspace.research["candidates"].values()))

    def test_natural_language_constraints_and_professional_sector(self):
        result = self.workspace.search_businesses({"question": "Find accounting firms with website issues and a public contact"})
        self.assertTrue(result["query"]["require_website_issue"])
        self.assertTrue(result["query"]["require_contact"])
        self.assertEqual([r["id"] for r in result["results"]], ["demo:accounting-issues"])
        offices = self.workspace.search_businesses({"segment": "professional"})
        self.assertEqual(offices["total"], 5)

    def test_responses_api_wire_format_and_usage_are_parsed(self):
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self, maximum):
                return json.dumps({"status": "completed", "output": [{"type": "message", "content": [{"type": "output_text", "text": '{"recommendations":[],"unknowns":["No suitable evidence"]}'}]}], "usage": {"input_tokens": 20, "output_tokens": 10}}).encode()
        with patch.dict('os.environ', {"OPENAI_API_KEY": "fixture-key", "VICALL_AI_MODEL": "fixture-model"}), patch('intelligence.urlopen', return_value=Response()) as request:
            answer, usage = generate_answer("question", [])
            sent = json.loads(request.call_args.args[0].data)
            self.assertFalse(sent["store"])
            self.assertEqual(sent["text"]["format"]["type"], "json_schema")
            self.assertEqual(sent["model"], "fixture-model")
            self.assertEqual(usage["input_tokens"], 20)
            self.assertEqual(answer["recommendations"], [])


if __name__ == "__main__":
    unittest.main()
