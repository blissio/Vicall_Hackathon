import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from collect_osm import clean, export, fetch, normalize, website


def element(identity=1, **tags):
    return {"type": "node", "id": identity, "lat": 40.44, "lon": -79.99,
            "tags": {"name": "Example Cafe", "amenity": "cafe", **tags}}


def envelope(elements):
    return {"collected_at": "2026-10-06T00:00:00+00:00", "payload": {"elements": elements}}


class CollectorTests(unittest.TestCase):
    def test_missing_website_is_unknown_and_no_address_is_invented(self):
        record, _ = normalize(element(), "today")
        self.assertEqual(record["website_status"], "not_listed_in_osm")
        self.assertIsNone(record["address"]["city"])
        self.assertEqual(record["ownership_status"], "unknown")

    def test_contact_aliases_and_invalid_values_preserved(self):
        record, _ = normalize(element(**{"contact:website": "EXAMPLE.com; javascript:alert(1)",
                                         "contact:phone": "(412) 555-0123; 412-555-0123 ext 9",
                                         "email": "info@example.com; invalid"}), "today")
        self.assertEqual(record["websites"], ["https://example.com/"])
        self.assertEqual(record["phones"], ["+14125550123"])
        self.assertEqual(len(record["contact_values_raw"]["phone"]), 2)
        self.assertIn("email_values_need_review", record["quality_flags"])

    def test_inactive_and_nonbusiness_features_excluded(self):
        for tags in ({"disused": "yes"}, {"amenity": "bench"},
                     {"amenity": "", "shop": "vacant"},
                     {"amenity": "", "office": "government"}):
            record, _ = normalize(element(**tags), "today")
            self.assertIsNone(record)

    def test_osm_identity_dedup_and_branch_preservation(self):
        nearby = element(2)
        nearby["type"] = "way"
        nearby["center"] = {"lat": nearby.pop("lat"), "lon": nearby.pop("lon")}
        branch = element(3)
        branch["lat"] = 40.5
        rows, report = clean(envelope([element(), element(), nearby, branch]))
        self.assertEqual(len(rows), 3)
        self.assertEqual(report["skipped"]["repeated_osm_id"], 1)
        by_id = {r["_id"]: r for r in rows}
        self.assertEqual(by_id["osm:node:1"]["duplicate_candidates"], ["osm:way:2"])
        self.assertEqual(by_id["osm:node:3"]["duplicate_candidates"], [])

    def test_bad_urls_are_not_fetchable_websites(self):
        for url in ("javascript:alert(1)", "https://x.com:bad", "https://user:secret@x.com", "x .com"):
            self.assertIsNone(website(url))

    def test_partial_overpass_response_rejected_without_caching(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            from io import BytesIO
            response = BytesIO(json.dumps({"elements": [], "remark": "runtime error: timeout"}).encode())
            with patch("collect_osm.urlopen", return_value=response):
                with self.assertRaisesRegex(ValueError, "incomplete"):
                    fetch("query", "https://example.com", Path(directory))
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_exports_are_repeatable_and_preserve_source(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            path = Path(directory)
            export(envelope([element(name="=HYPERLINK(1)")]), path)
            first = (path / "processed/businesses.jsonl").read_text(encoding="utf-8")
            export(envelope([element(name="=HYPERLINK(1)")]), path)
            self.assertEqual(first, (path / "processed/businesses.jsonl").read_text(encoding="utf-8"))
            self.assertIn("https://www.openstreetmap.org/node/1", first)
            self.assertIn("'=HYPERLINK", (path / "processed/businesses.csv").read_text(encoding="utf-8-sig"))


if __name__ == "__main__":
    unittest.main()
