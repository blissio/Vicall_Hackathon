"""Persistent research jobs, source inbox, and service-area business records."""
import csv
import io
import json
import os
import threading
from datetime import datetime, timezone

from business_research import SOURCES, ResearchCrawler, contact_claims, enrich_business, fetch_directory, normalized_name, social_platform, stamp, status_summary, phone, email
from website_audit import clean_url


def save_json(path, value):
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, path)


def age_hours(value):
    try:
        return (datetime.now(timezone.utc)-datetime.fromisoformat(value)).total_seconds()/3600
    except (TypeError, ValueError):
        return float("inf")


class ResearchWorkspace:
    def init_research(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        self.research_file = self.directory / "business_research.json"
        self.research = json.loads(self.research_file.read_text(encoding="utf-8")) if self.research_file.exists() else {"enrichments": {}, "candidates": {}, "external": {}, "sources": {}, "settings": {"enabled": True, "interval_hours": 24, "batch_size": 5, "sources": ["city_businesses", "city_contractors"]}}
        if not isinstance(self.research, dict) or any(not isinstance(self.research.get(k), dict) for k in ("enrichments", "candidates", "external", "sources", "settings")):
            raise ValueError("business_research.json has an invalid structure")
        self.research_job_file = self.directory / "research_job.json"
        self.research_job = json.loads(self.research_job_file.read_text(encoding="utf-8")) if self.research_job_file.exists() else {"status": "idle", "message": "Ready for automated research", "completed": 0, "total": 0}
        if self.research_job.get("status") == "running":
            self.research_job.update(status="interrupted", message="Previous research was interrupted. Saved findings remain; run again to continue.")
            save_json(self.research_job_file, self.research_job)
        self.research_cancel = threading.Event()
        self.automation_stop = threading.Event()

    def decorate_business(self, row):
        row = dict(row)
        enrichment = self.research["enrichments"].get(row["_id"])
        claims = contact_claims(row, enrichment)
        summary = status_summary(row, row["workflow"], row.get("audit"), enrichment)
        # Preserve field-level sources while making observed channels searchable.
        for kind, field in (("phone", "phones"), ("email", "emails"), ("social", "social_urls")):
            row[field] = list(dict.fromkeys(c["value"] for c in claims if c["kind"] == kind))
        row["contact_evidence"] = claims
        row["contact_pages"] = list(dict.fromkeys(c["value"] for c in claims if c["kind"] in {"contact_page", "contact_form"}))
        row["research_status"] = summary
        row["enrichment"] = enrichment
        return row

    def research_status(self):
        with self.lock:
            candidates = []
            by_name = {}
            for row in self.rows:
                by_name.setdefault(normalized_name(row["name"]), []).append({"id": row["_id"], "name": row["name"]})
            for candidate in self.research["candidates"].values():
                item = dict(candidate)
                item["possible_matches"] = [r for r in by_name.get(normalized_name(item["name"]), []) if r["id"] != item.get("added_id")][:10]
                candidates.append(item)
            return {"job": dict(self.research_job), "settings": dict(self.research["settings"]), "sources": self.research["sources"], "candidates": candidates,
                    "providers": [{"key": k, "name": s["name"]} for k, s in SOURCES.items()], "enriched": len(self.research["enrichments"])}

    def configure_research(self, payload):
        allowed = {"enabled", "interval_hours", "batch_size", "sources"}
        if set(payload)-allowed:
            raise ValueError("Unknown automation setting")
        candidate = {**self.research["settings"], **payload}
        if not isinstance(candidate["enabled"], bool) or isinstance(candidate["interval_hours"], bool) or not isinstance(candidate["interval_hours"], int) or not 6 <= candidate["interval_hours"] <= 168:
            raise ValueError("Choose an interval from 6 to 168 hours")
        if isinstance(candidate["batch_size"], bool) or not isinstance(candidate["batch_size"], int) or not 1 <= candidate["batch_size"] <= 25:
            raise ValueError("Choose 1–25 websites per automatic batch")
        if not isinstance(candidate["sources"], list) or any(k not in SOURCES for k in candidate["sources"]):
            raise ValueError("Unknown directory source")
        with self.lock:
            updated = {**self.research, "settings": candidate}
            save_json(self.research_file, updated)
            self.research = updated
        return candidate

    def start_research(self, payload):
        ids = payload.get("ids", [])
        sources = payload.get("sources", [])
        force = payload.get("force", False)
        if not isinstance(ids, list) or len(ids) > 25 or any(not isinstance(i, str) for i in ids):
            raise ValueError("Choose up to 25 businesses for research")
        if not isinstance(sources, list) or any(not isinstance(k, str) or k not in SOURCES for k in sources):
            raise ValueError("Choose supported public directories")
        if not isinstance(force, bool) or not (ids or sources):
            raise ValueError("Choose businesses or a directory source")
        with self.lock:
            if self.research_job["status"] == "running" or self.audit_job["status"] == "running":
                raise ValueError("Wait for the current website/research batch, or stop it first")
            targets, skipped = [], 0
            for identity in dict.fromkeys(ids):
                if identity not in self.by_id:
                    raise KeyError("Business not found")
                business = dict(self.by_id[identity])
                audit = self.audits.get(identity, {}).get("latest", {})
                urls = [audit.get("requested_url"), *business.get("websites", [])]
                url = next((u for u in urls if u and not social_platform(u)), None)
                previous = self.research["enrichments"].get(identity, {})
                if not url or not force and previous.get("requested_url") == url and 0 <= age_hours(previous.get("checked_at")) < 24:
                    skipped += 1
                    continue
                targets.append({"id": identity, "url": clean_url(url), "business": business})
            self.research_cancel.clear()
            self.research_job = {"status": "running", "message": "Starting public-source research…", "started_at": stamp(), "completed": 0, "total": len(targets)+len(set(sources)), "skipped": skipped, "ids": [t["id"] for t in targets], "sources": list(dict.fromkeys(sources)), "errors": [], "results": []}
            save_json(self.research_job_file, self.research_job)
        threading.Thread(target=self._run_research, args=(targets, list(dict.fromkeys(sources))), daemon=True).start()
        return dict(self.research_job)

    def cancel_research(self):
        self.research_cancel.set()
        with self.lock:
            if self.research_job["status"] == "running":
                self.research_job["message"] = "Stopping after the current business/source; completed findings are saved"
                save_json(self.research_job_file, self.research_job)
            return dict(self.research_job)

    def _run_research(self, targets, sources):
        try:
            crawler = ResearchCrawler()
            for kind, target in [("source", s) for s in sources]+[("website", t) for t in targets]:
                if self.research_cancel.is_set():
                    break
                name = SOURCES[target]["name"] if kind == "source" else target["business"]["name"]
                with self.lock:
                    self.research_job["message"] = "Researching "+name+"…"
                try:
                    if kind == "source":
                        candidates, summary = fetch_directory(target)
                        with self.lock:
                            inbox = dict(self.research["candidates"])
                            for item in candidates:
                                existing = inbox.get(item["id"], {})
                                inbox[item["id"]] = {**item, **{k: existing[k] for k in ("review_status", "added_id") if k in existing}}
                            updated = {**self.research, "candidates": inbox, "sources": {**self.research["sources"], target: summary}}
                            save_json(self.research_file, updated)
                            self.research = updated
                    else:
                        result = enrich_business(target["business"], target["url"], crawler)
                        with self.lock:
                            updated = {**self.research, "enrichments": {**self.research["enrichments"], target["id"]: result}}
                            save_json(self.research_file, updated)
                            self.research = updated
                            self.research_job["results"].append(target["id"])
                except Exception as exc:
                    with self.lock:
                        self.research_job["errors"].append({"target": name, "message": str(exc)[:200]})
                with self.lock:
                    self.research_job["completed"] += 1
                    save_json(self.research_job_file, self.research_job)
            with self.lock:
                stopped = self.research_cancel.is_set()
                errors = len(self.research_job["errors"])
                self.research_job.update(status="cancelled" if stopped else "complete_with_errors" if errors else "complete", message=f"{'Stopped' if stopped else 'Finished'} · {self.research_job['completed']} research tasks · {errors} errors", finished_at=stamp())
                save_json(self.research_job_file, self.research_job)
        except Exception as exc:
            with self.lock:
                self.research_job.update(status="failed", message="Research stopped; completed findings remain saved", error=str(exc)[:200])
                save_json(self.research_job_file, self.research_job)

    def add_candidate(self, payload):
        name = payload.get("name")
        source = payload.get("source_url")
        if not isinstance(name, str) or not 2 <= len(name.strip()) <= 200 or not isinstance(source, str):
            raise ValueError("A business name and public source URL are required")
        source = clean_url(source)
        location_type = payload.get("location_type", "unknown")
        if location_type not in {"unknown", "home_based", "service_area", "storefront", "online_only"}:
            raise ValueError("Unknown location type")
        for key in ("service_area", "category", "website", "phone", "email", "social_url"):
            if key in payload and (not isinstance(payload[key], str) or len(payload[key]) > 2048):
                raise ValueError("Invalid listing field")
        sites, socials = [], []
        for raw in [payload.get("website"), payload.get("social_url")]:
            if raw:
                url = clean_url(raw if "://" in raw else "https://"+raw)
                (socials if social_platform(url) else sites).append(url)
        import hashlib
        identity = "submitted:"+hashlib.sha256((normalized_name(name)+source).encode()).hexdigest()[:20]
        candidate = {"id": identity, "name": name.strip(), "category": payload.get("category") or "Service business", "websites": sites, "social_urls": socials,
                     "phones": [v] if (v := phone(payload.get("phone", ""))) else [], "emails": [v] if (v := email(payload.get("email", ""))) else [],
                     "location_type": location_type, "service_area": payload.get("service_area") or "Unconfirmed", "source": {"provider": "Researcher-submitted public listing", "url": source, "collected_at": stamp()},
                     "review_status": "new", "scope_status": "needs_review", "business_status": "unknown"}
        if payload.get("email") and not candidate["emails"] or payload.get("phone") and not candidate["phones"]:
            raise ValueError("Check the email/US telephone format")
        with self.lock:
            previous = self.research["candidates"].get(identity)
            if previous:
                return {"candidate": previous, "created": False}
            updated = {**self.research, "candidates": {**self.research["candidates"], identity: candidate}}
            save_json(self.research_file, updated)
            self.research = updated
        return {"candidate": candidate, "created": True}

    def import_candidates(self, payload):
        content = payload.get("csv")
        if not isinstance(content, str) or len(content) > 500000:
            raise ValueError("Choose a CSV under 500 KB")
        records = list(csv.DictReader(io.StringIO(content.lstrip("\ufeff"))))
        if not 1 <= len(records) <= 200:
            raise ValueError("Import 1–200 business listings at a time")
        results = {"added": 0, "existing": 0, "errors": []}
        for number, row in enumerate(records, 2):
            try:
                result = self.add_candidate(row)
                results["added" if result["created"] else "existing"] += 1
            except (ValueError, TypeError) as exc:
                results["errors"].append({"row": number, "message": str(exc)})
        return results

    def review_candidate(self, payload):
        identity = payload.get("id")
        action = payload.get("action")
        if not isinstance(identity, str) or action not in {"add", "dismiss", "restore"}:
            raise ValueError("Choose a candidate and review action")
        with self.lock:
            candidate = self.research["candidates"].get(identity)
            if not candidate:
                raise KeyError("Candidate not found")
            candidate = dict(candidate)
            external = dict(self.research["external"])
            if action == "add":
                business_id = "lead:"+identity
                external.setdefault(business_id, {"_id": business_id, "name": candidate["name"], "category": "external:"+candidate["category"], "address": {}, "location": None, "coordinate_method": "not_mapped",
                    "websites": candidate["websites"], "website_status": "listed_external_unverified" if candidate["websites"] else "not_listed_in_osm", "phones": candidate["phones"], "emails": candidate["emails"], "social_urls": candidate.get("social_urls", []),
                    "location_type": candidate["location_type"], "service_area": candidate["service_area"], "quality_flags": ["identity_and_service_area_need_review"], "duplicate_candidates": [], "source": candidate["source"], "license_evidence": candidate.get("license_evidence", {})})
                candidate.update(review_status="added", added_id=business_id)
            else:
                candidate["review_status"] = "dismissed" if action == "dismiss" else "new"
            updated = {**self.research, "external": external, "candidates": {**self.research["candidates"], identity: candidate}}
            save_json(self.research_file, updated)
            self.research = updated
            self.reload()
            return candidate

    def start_automation(self):
        def loop():
            if self.automation_stop.wait(3):
                return
            while not self.automation_stop.is_set():
                with self.lock:
                    settings = self.research["settings"]
                    due = age_hours(settings.get("last_started_at")) >= settings["interval_hours"]
                    busy = self.research_job["status"] == "running" or self.audit_job["status"] == "running" or self.job["status"] == "running"
                    if settings["enabled"] and due and not busy:
                        sources = [k for k in settings["sources"] if age_hours(self.research["sources"].get(k, {}).get("observed_at")) >= settings["interval_hours"]]
                        ids = [r["_id"] for r in self.rows if any(not social_platform(u) for u in r.get("websites", [])) and age_hours(self.research["enrichments"].get(r["_id"], {}).get("checked_at")) >= settings["interval_hours"]][:settings["batch_size"]]
                        if ids or sources:
                            try:
                                self.start_research({"ids": ids, "sources": sources})
                                updated = {**self.research, "settings": {**settings, "last_started_at": stamp()}}
                                save_json(self.research_file, updated)
                                self.research = updated
                            except (ValueError, OSError):
                                pass
                if self.automation_stop.wait(30):
                    break
        threading.Thread(target=loop, daemon=True).start()
