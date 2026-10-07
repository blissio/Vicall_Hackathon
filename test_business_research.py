import json
import unittest
from urllib.parse import parse_qs, urlsplit

from business_research import ResearchCrawler, enrich_business, extract_contacts, fetch_directory, status_summary


def page(text, url="https://example.com/", status=200, content_type="text/html"):
    return {"text": text, "url": url, "status": status, "headers": {"content-type": content_type}, "truncated": False}


class Fetcher:
    def __init__(self, pages):
        self.pages, self.calls, self.delays = pages, [], {}

    def reset_budget(self):
        pass

    def get(self, url, limit=None, before_request=None):
        if before_request:
            before_request(url)
        self.calls.append(url)
        return self.pages.get(url, page("", url, 404))


class ResearchTests(unittest.TestCase):
    def test_explicit_contacts_with_provenance_and_no_person_schema(self):
        html = '''<a href="mailto:hello@example.com?subject=Hello">Email</a><a href="tel:(412)555-0100">Call</a>
        <a href="https://facebook.com/examplebusiness">Facebook</a><a href="https://facebook.com/sharer.php?u=x">Share</a>
        <a href="/contact">Contact us</a><a href="https://other.example/contact">Other site</a>
        <script type="application/ld+json">{"@type":"Person","email":"personal@example.com"}</script>
        <script type="application/ld+json">{"@type":"Organization","telephone":"4125550100"}</script>'''
        claims, links, text = extract_contacts(page(html), "2026-10-06T00:00:00+00:00")
        self.assertEqual({c["value"] for c in claims if c["kind"] == "email"}, {"hello@example.com"})
        self.assertEqual(len([c for c in claims if c["kind"] == "phone"]), 1)
        self.assertEqual(len([c for c in claims if c["kind"] == "social"]), 1)
        self.assertEqual(links, ["https://example.com/contact"])
        self.assertTrue(all(c["source_url"] == "https://example.com/" for c in claims))

    def test_crawl_contacts_about_pages_bounded_and_preserves_unknown_identity(self):
        fetcher = Fetcher({"https://example.com/robots.txt": page("User-agent: *\nDisallow: /private", "https://example.com/robots.txt"),
            "https://example.com/": page('<h1>Test Cafe</h1><a href="/contact">Contact</a><a href="/private/about">About</a>'),
            "https://example.com/contact": page('<a href="mailto:hello@example.com">Email</a><form action="/contact/send"></form>', "https://example.com/contact")})
        result = enrich_business({"name": "Test Cafe"}, "https://example.com/", ResearchCrawler(fetcher))
        self.assertEqual(result["identity"], "unverified")
        self.assertTrue(result["identity_signals"])
        self.assertIn("hello@example.com", [c["value"] for c in result["contacts"]])
        self.assertNotIn("https://example.com/private/about", fetcher.calls)
        self.assertLessEqual(len(result["pages"]), 4)

    def test_social_targets_are_manual_only_and_errors_do_not_mean_closed(self):
        fetcher = Fetcher({})
        result = enrich_business({"name": "Home Business"}, "https://facebook.com/marketplace/item/123", ResearchCrawler(fetcher))
        self.assertEqual(fetcher.calls, [])
        self.assertEqual(result["status"], "inconclusive")
        status = status_summary({"websites": ["https://example.com/"], "source": {}, "phones": []}, {}, {"reachability": "unreachable", "requested_url": "https://example.com/"})
        self.assertEqual(status["business"], "unknown")
        self.assertEqual(status["website"], "unreachable")

    def test_license_import_public_projection_no_address_or_owner_inferences(self):
        class DirectoryFetcher(Fetcher):
            def get(self, url, **kwargs):
                self.calls.append(url)
                params = parse_qs(urlsplit(url).query)
                self_test.assertEqual(json.loads(params["filters"][0]), {"license_state": "Active"})
                self_test.assertNotIn("address", params["fields"][0].split(","))
                data = {"success": True, "result": {"total": 1, "records": [{"business_name": "Home Baker LLC", "license_number": "L1", "license_state": "Active", "expiration_date": "2020-01-01", "email_address": "business@example.com", "address": "Private address"}]}}
                return page(json.dumps(data), url, content_type="application/json")
        self_test = self
        rows, summary = fetch_directory("city_businesses", DirectoryFetcher({}))
        self.assertEqual(rows[0]["business_status"], "unknown")
        self.assertEqual(rows[0]["location_type"], "unknown")
        self.assertNotIn("Private address", json.dumps(rows))
        self.assertEqual(rows[0]["emails"], ["business@example.com"])
        self.assertEqual(rows[0]["license_evidence"]["state"], "Active")
        self.assertFalse(summary["limited"])

    def test_identity_confirmation_is_url_scoped(self):
        row = {"websites": [], "source": {}}
        workflow = {"website_identity": "confirmed", "identity_url": "https://example.com/"}
        self.assertEqual(status_summary(row, workflow, {"requested_url": "https://example.com/", "reachability": "reachable"})["identity"], "researcher_confirmed")
        self.assertEqual(status_summary(row, workflow, {"requested_url": "https://other.example/", "reachability": "reachable"})["identity"], "unverified")

    def test_latest_page_observation_and_contact_differences_are_distinct_from_operation(self):
        row = {"websites": ["https://example.com/"], "phones": ["+14125550100"], "source": {}}
        audit = {"requested_url": "https://example.com/", "reachability": "reachable", "checked_at": "2026-10-05T00:00:00+00:00"}
        enrichment = {"requested_url": "https://example.com/", "checked_at": "2026-10-06T00:00:00+00:00", "pages": [{"outcome": "http_error", "http_status": 404}], "contacts": [{"kind": "phone", "value": "+14125550199"}]}
        summary = status_summary(row, {}, audit, enrichment)
        self.assertEqual(summary["website"], "http_error")
        self.assertEqual(summary["website_check_source"], "Public-page research")
        self.assertEqual(summary["business"], "unknown")
        self.assertEqual(summary["contact_disagreements"], ["phone"])


if __name__ == "__main__":
    unittest.main()
