"""Vicall local graphical application. Run: python app.py"""
import argparse
import csv
import io
import json
import logging
import os
import secrets
import shutil
import subprocess
import sys
import threading
import webbrowser
from collections import Counter
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
from urllib.parse import parse_qs

from website_audit import VERSION as AUDIT_VERSION, PublicFetcher, audit_website, clean_url
from neighborhoods import SOURCE_URL as NEIGHBORHOOD_SOURCE, enrich_neighborhoods
from research_workspace import ResearchWorkspace
from storage import load_document, save_document, connect
from intelligence import IntelligenceWorkspace

ROOT = Path(__file__).resolve().parent
STAGES = ("New", "Researching", "Qualified", "Not a fit")


class AppAlreadyRunning(Exception):
    def __init__(self, url):
        self.url = url
        super().__init__("This workspace is already open in Vicall")


class CollectionCancelled(Exception):
    pass


def lock_workspace(directory):
    directory.mkdir(parents=True, exist_ok=True)
    handle = (directory / ".app.lock").open("a+b")
    handle.seek(0, 2)
    if not handle.tell():
        handle.write(b"0")
        handle.flush()
    handle.seek(0)
    try:
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        url = None
        try:
            port = json.loads((directory / ".app-instance.json").read_text(encoding="utf-8"))["port"]
            if isinstance(port, int) and 1 <= port <= 65535:
                url = f"http://127.0.0.1:{port}"
        except (OSError, ValueError, KeyError):
            pass
        raise AppAlreadyRunning(url)
    return handle


class LocalServer(ThreadingHTTPServer):
    def server_close(self):
        super().server_close()
        if getattr(self, "workspace_lock", None):
            self.workspace_lock.close()
            self.workspace_lock = None


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path, value):
    save_document(path, value)


class Workspace(IntelligenceWorkspace, ResearchWorkspace):
    def __init__(self, directory):
        self.directory = Path(directory).resolve()
        self.lock = threading.RLock()
        self.rows = []
        self.by_id = {}
        self.report = {}
        self.load_error = None
        self.workflow_file = self.directory / "workspace.json"
        self.workflow = {}
        self.workflow = load_document(self.workflow_file, {})
        # Never silently overwrite unreadable research notes.
        if not isinstance(self.workflow, dict):
            raise ValueError("workspace.json must contain an object")
        self.collection_job_file = self.directory / 'collection_job.json'
        self.job = load_document(self.collection_job_file, {"status": "idle", "message": "Ready", "log": ""})
        if self.job.get('status') == 'running':
            self.job.update(status='interrupted', message='Collection interrupted. Resume using saved partial responses or start a fresh run.')
            atomic_json(self.collection_job_file, self.job)
        self.collection_cancel = threading.Event()
        self.audits_file = self.directory / "website_audits.json"
        self.audits = load_document(self.audits_file, {})
        if not isinstance(self.audits, dict):
            raise ValueError("website_audits.json must contain an object")
        self.audit_job_file = self.directory / "audit_job.json"
        self.audit_job = load_document(self.audit_job_file, {"status": "idle", "message": "Ready to analyze websites", "completed": 0, "total": 0, "skipped": 0})
        if self.audit_job.get("status") == "running":
            self.audit_job.update(status="interrupted", message="Previous audit batch interrupted; resume unfinished audits")
            atomic_json(self.audit_job_file, self.audit_job)
        self.audit_cancel = threading.Event()
        self.init_research()
        self.reload()

    def reload(self):
        active = load_document(self.directory / "active_dataset.json", {})
        base = self.directory
        if active.get("relative_path"):
            base = (self.directory / active["relative_path"]).resolve()
            if not base.is_relative_to(self.directory):
                raise ValueError("Active dataset must stay within the data directory")
        path = base / "processed" / "businesses.jsonl"
        try:
            rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()] if path.exists() else []
            rows += list(self.research["external"].values())
            if any(not isinstance(r, dict) or not r.get("_id") or not r.get("name") for r in rows):
                raise ValueError("Dataset contains a record without an ID or name")
            if len({r["_id"] for r in rows}) != len(rows):
                raise ValueError("Dataset contains duplicate source IDs")
            enrich_neighborhoods(rows)
            report_path = base / "processed" / "quality_report.json"
            report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else {}
            with self.lock:
                with connect(self.directory) as db:
                    db.execute("DELETE FROM organizations")
                    db.executemany("INSERT INTO organizations VALUES (?,?)", ((row["_id"], json.dumps(row)) for row in rows))
                    db.execute("INSERT OR REPLACE INTO metadata VALUES ('dataset_report',?)", (json.dumps(report),))
                self.rows = rows
                self.by_id = {r["_id"]: r for r in rows}
                self.report = report
                self.load_error = None
        except (OSError, ValueError) as exc:
            self.load_error = f"Could not load saved data: {exc}"

    def data(self):
        with self.lock:
            # raw_tags stay in the original JSONL; keep the directory payload light.
            businesses = []
            for r in self.rows:
                copy = {k: v for k, v in r.items() if k not in {"raw_tags", "contact_values_raw"}}
                copy["workflow"] = {"shortlisted": False, "stage": "New", "notes": "",
                                    **self.workflow.get(r["_id"], {})}
                latest = self.audits.get(r["_id"], {}).get("latest")
                copy["audit"] = {key: latest.get(key) for key in ("reachability", "score", "grade", "checked_at", "requested_url", "final_url", "http_status", "message", "audit_version")} if latest else None
                businesses.append(self.decorate_business(copy))
            return {"businesses": businesses, "report": self.report, "error": self.load_error, "demo": (self.directory / "DEMO.json").exists(), "audit_version": AUDIT_VERSION, "neighborhood_source": NEIGHBORHOOD_SOURCE,
                    "summary": {"total": len(businesses),
                                "websites": sum(bool(r.get("websites")) for r in businesses),
                                "emails": sum(bool(r.get("emails")) for r in businesses),
                                "phones": sum(bool(r.get("phones")) for r in businesses),
                                "duplicates": sum(bool(r.get("duplicate_candidates")) for r in businesses),
                                "shortlisted": sum(bool(r["workflow"]["shortlisted"]) for r in businesses),
                                "stages": dict(Counter(r["workflow"]["stage"] for r in businesses))}}

    def update(self, payload):
        identity = payload.get("id")
        if not isinstance(identity, str):
            raise ValueError("A business ID is required")
        patch = {key: value for key, value in payload.items() if key in {"shortlisted", "stage", "notes", "business_status", "business_evidence", "website_identity", "identity_evidence", "identity_url"}}
        if not patch:
            raise ValueError("No research changes supplied")
        if "shortlisted" in patch and not isinstance(patch["shortlisted"], bool):
            raise ValueError("Shortlisted must be true or false")
        if "stage" in patch and patch["stage"] not in STAGES:
            raise ValueError("Unknown research stage")
        if "notes" in patch and (not isinstance(patch["notes"], str) or len(patch["notes"]) > 12000):
            raise ValueError("Notes must be text, up to 12,000 characters")
        if "business_status" in patch and patch["business_status"] not in {"unknown", "operating", "temporarily_closed", "permanently_closed"}:
            raise ValueError("Unknown business status")
        if "website_identity" in patch and patch["website_identity"] not in {"unverified", "confirmed"}:
            raise ValueError("Unknown website identity status")
        for key in ("business_evidence", "identity_evidence", "identity_url"):
            if key in patch and (not isinstance(patch[key], str) or len(patch[key]) > 3000):
                raise ValueError("Evidence must be text up to 3,000 characters")
        with self.lock:
            if identity not in self.by_id:
                raise KeyError("Business no longer exists in the current dataset")
            combined = {**self.workflow.get(identity, {}), **patch}
            if "expected_updated_at" in payload and payload["expected_updated_at"] != self.workflow.get(identity, {}).get("updated_at"):
                raise ValueError("This research was changed by another session. Reload before saving.")
            if patch.get("business_status", "unknown") != "unknown" and not combined.get("business_evidence", "").strip():
                raise ValueError("Add dated/source evidence before assigning an operating or closed status")
            if patch.get("website_identity") == "confirmed":
                if not combined.get("identity_evidence", "").strip() or not combined.get("identity_url"):
                    raise ValueError("Add the matched website URL and identity evidence")
                patch["identity_url"] = clean_url(combined["identity_url"])
            if "business_status" in patch:
                patch["business_checked_at"] = timestamp()
            updated = {**self.workflow.get(identity, {}), **patch, "updated_at": timestamp()}
            candidate = {**self.workflow, identity: updated}
            atomic_json(self.workflow_file, candidate)
            self.workflow = candidate
            return {"shortlisted": False, "stage": "New", "notes": "", **updated}

    def export_csv(self, identities):
        if not isinstance(identities, list) or len(identities) > 100000 or any(not isinstance(i, str) for i in identities):
            raise ValueError("Export requires a list of business IDs")
        buffer = io.StringIO(newline="")
        fields = ["name", "category", "neighborhood", "neighborhood_method", "neighborhood_source", "street_address", "city", "postcode", "websites", "website_status",
                  "phones", "emails", "research_stage", "shortlisted", "notes", "source_url", "attribution", "license_url",
                  "audited_url", "website_reachability", "http_status", "technical_seo_score", "seo_grade", "audit_date", "suggested_improvements",
                  "business_status", "business_evidence", "website_identity", "identity_evidence", "location_type", "service_area", "social_urls", "contact_pages", "contact_evidence_json", "enrichment_date", "website_checked_at", "website_check_source", "contact_disagreements"]
        fields += ["organization_type", "services", "parent_id", "people_evidence_json", 'extended_audits_json']
        writer = csv.DictWriter(buffer, fieldnames=fields)
        writer.writeheader()
        with self.lock:
            records = self.intelligence_records(identities)
            for identity in dict.fromkeys(identities):
                if identity not in self.by_id:
                    continue
                r = self.by_id[identity]
                a, w = r.get("address", {}), self.workflow.get(identity, {})
                audit = self.audits.get(identity, {}).get("latest", {})
                enriched = self.decorate_business({**r, "workflow": w, "audit": audit or None})
                row = {"name": r["name"], "category": r.get("category", ""),
                       "neighborhood": r.get("neighborhood"), "neighborhood_method": r.get("neighborhood_method"), "neighborhood_source": NEIGHBORHOOD_SOURCE,
                       "street_address": " ".join(a.get(k) or "" for k in ("house_number", "street", "unit")).strip(),
                       "city": a.get("city"), "postcode": a.get("postcode"),
                       "websites": "; ".join(r.get("websites", [])), "website_status": r.get("website_status"),
                       "phones": "; ".join(enriched.get("phones", [])), "emails": "; ".join(enriched.get("emails", [])),
                       "research_stage": w.get("stage", "New"), "shortlisted": w.get("shortlisted", False),
                       "notes": w.get("notes", ""), "source_url": r.get("source", {}).get("url", ""),
                       "attribution": "© OpenStreetMap contributors", "license_url": "https://www.openstreetmap.org/copyright",
                       "audited_url": audit.get("requested_url"), "website_reachability": enriched["research_status"]["website"],
                       "http_status": audit.get("http_status"), "technical_seo_score": audit.get("score"),
                       "seo_grade": audit.get("grade"), "audit_date": audit.get("checked_at"),
                       "suggested_improvements": " | ".join(c.get("recommendation", "") for c in audit.get("recommendations", [])),
                       "business_status": enriched["research_status"]["business"], "business_evidence": w.get("business_evidence", ""), "website_identity": enriched["research_status"]["identity"], "identity_evidence": w.get("identity_evidence", ""),
                       "location_type": enriched["research_status"]["location_type"], "service_area": r.get("service_area", ""), "social_urls": "; ".join(enriched["social_urls"]), "contact_pages": "; ".join(enriched["contact_pages"]),
                       "contact_evidence_json": json.dumps(enriched["contact_evidence"], ensure_ascii=False), "enrichment_date": enriched["research_status"].get("enrichment_checked_at"),
                       "website_checked_at": enriched["research_status"].get("website_checked_at"), "website_check_source": enriched["research_status"].get("website_check_source"), "contact_disagreements": "; ".join(enriched["research_status"]["contact_disagreements"])}
                detail = self.intelligence_detail(identity, records)
                row.update(organization_type=detail["review"].get("organization_type", "business"), services=detail["review"].get("services", ""), parent_id=detail["review"].get("parent_id", ""), people_evidence_json=json.dumps(detail["contacts"], ensure_ascii=False))
                row['extended_audits_json'] = json.dumps(detail['extended_audits'], ensure_ascii=False)
                if not identity.startswith("osm:"):
                    row["attribution"] = r.get("source", {}).get("provider", "Researcher-submitted public listing")
                    row["license_url"] = r.get("source", {}).get("license_url", "")
                writer.writerow({k: "'" + v if isinstance(v, str) and v.lstrip().startswith(("=", "+", "-", "@")) else v for k, v in row.items()})
        return ("\ufeff" + buffer.getvalue()).encode("utf-8")

    def start_job(self, mode):
        if mode not in {"collect", "refresh", "clean"}:
            raise ValueError("Unknown collection action")
        if mode == "clean" and not (self.directory / "raw" / "businesses.json").exists():
            raise ValueError("Collect data before rebuilding the saved snapshot")
        with self.lock:
            if self.job["status"] == "running":
                raise ValueError("A collection job is already running")
            self.job = {"status": "running", "mode": mode, "started_at": timestamp(),
                        "message": "Rebuilding saved data…" if mode == "clean" else "Requesting Pittsburgh data from OpenStreetMap…", "log": ""}
            self.collection_cancel.clear()
            atomic_json(self.collection_job_file, self.job)
        threading.Thread(target=self._run_job, args=(mode,), daemon=True).start()
        return self.job_status()

    def job_status(self):
        with self.lock:
            return dict(self.job)

    def cancel_collection(self):
        with self.lock:
            if self.job['status'] == 'running':
                self.collection_cancel.set()
                self.job['message'] = 'Stopping collection; your published dataset remains available'
                atomic_json(self.collection_job_file, self.job)
            return dict(self.job)

    def resume_collection(self):
        with self.lock:
            if self.job['status'] not in {'interrupted', 'cancelled', 'failed'}:
                raise ValueError('No unfinished collection to resume')
            staging = self.job.get('staging')
            if staging:
                source = (self.directory / staging / 'cache').resolve()
                if not source.is_relative_to(self.directory / 'jobs'):
                    raise ValueError('Saved collection must stay within the jobs folder')
                if source.exists():
                    shutil.copytree(source, self.directory / 'cache', dirs_exist_ok=True)
        return self.start_job('clean' if self.job.get('mode') == 'clean' else 'collect')

    def _execute_collector(self, command, output):
        from time import monotonic
        process = subprocess.Popen(command, cwd=ROOT, stdout=output, stderr=subprocess.STDOUT,
            text=True, encoding='utf-8', errors='replace', env={**os.environ, 'PYTHONIOENCODING': 'utf-8'},
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        started = monotonic()
        try:
            while process.poll() is None:
                if self.collection_cancel.wait(0.2):
                    raise CollectionCancelled('Collection cancelled; saved responses can be resumed')
                if monotonic()-started > 600:
                    raise subprocess.TimeoutExpired(command, 600)
            return subprocess.CompletedProcess(command, process.returncode, '', '')
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)

    def audit_report(self, identity):
        with self.lock:
            if identity not in self.by_id:
                raise KeyError("Business not found")
            return self.audits.get(identity, {"latest": None, "history": []})

    def audit_status(self):
        with self.lock:
            return dict(self.audit_job)

    def cancel_audits(self):
        with self.lock:
            if self.audit_job["status"] == "running":
                self.audit_cancel.set()
                self.audit_job["message"] = "Stopping after the current website finishes…"
            return dict(self.audit_job)

    def start_audits(self, payload):
        ids = payload.get("ids")
        if not isinstance(ids, list) or not 1 <= len(ids) <= 25 or any(not isinstance(i, str) for i in ids):
            raise ValueError("Choose between 1 and 25 businesses for each audit batch")
        if "url" in payload and (len(ids) != 1 or not isinstance(payload["url"], str)):
            raise ValueError("A custom URL can be checked for one business at a time")
        if "force" in payload and not isinstance(payload["force"], bool):
            raise ValueError("Force must be true or false")
        force = payload.get("force", False)
        with self.lock:
            if self.audit_job["status"] == "running" or self.research_job["status"] == "running" or getattr(self, 'rendered_running', False) or getattr(self, 'extra_active', None):
                raise ValueError("A website/research batch is already running")
            targets, skipped = [], 0
            for identity in dict.fromkeys(ids):
                if identity not in self.by_id:
                    raise KeyError("Business not found")
                business = self.by_id[identity]
                latest = self.audits.get(identity, {}).get("latest", {})
                raw_url = payload.get("url") or latest.get("requested_url") or next(iter(business.get("websites", [])), None)
                if not raw_url:
                    skipped += 1
                    continue
                url = clean_url(raw_url)
                try:
                    age = (datetime.now(timezone.utc) - datetime.fromisoformat(latest.get("checked_at", ""))).total_seconds()
                except (ValueError, TypeError):
                    age = float("inf")
                if not force and latest.get("requested_url") == url and latest.get("audit_version") == AUDIT_VERSION and 0 <= age < 86400:
                    skipped += 1
                    continue
                targets.append({"id": identity, "url": url, "name": business["name"],
                                "target_source": ("listed_in_osm" if identity.startswith("osm:") else "listed_external") if url in business.get("websites", []) else "user_supplied"})
            self.audit_cancel.clear()
            self.audit_job = {"status": "running" if targets else "complete", "message": "Starting website analysis…" if targets else "No new checks needed. Missing URLs or results under 24 hours old were skipped.",
                              "completed": 0, "total": len(targets), "skipped": skipped, "started_at": timestamp(), "current_name": None,
                              "ids": [t["id"] for t in targets], "results": [], "pending_targets": targets.copy()}
            atomic_json(self.audit_job_file, self.audit_job)
        if targets:
            threading.Thread(target=self._run_audits, args=(targets,), daemon=True).start()
        return self.audit_status()

    def _run_audits(self, targets):
        try:
            fetcher = PublicFetcher()
            for target in targets:
                if self.audit_cancel.is_set():
                    break
                with self.lock:
                    self.audit_job.update(current_name=target["name"], message=f"Analyzing {target['name']}…")
                result = audit_website(target["url"], fetcher=fetcher)
                result.update(business_id=target["id"], business_name=target["name"], target_source=target["target_source"],
                              identity_status="unverified")
                with self.lock:
                    previous = self.audits.get(target["id"], {})
                    history = ([previous["latest"]] if previous.get("latest") else []) + previous.get("history", [])
                    updated = {**self.audits, target["id"]: {"latest": result, "history": history[:4]}}
                    atomic_json(self.audits_file, updated)
                    self.audits = updated
                    self.audit_job["completed"] += 1
                    self.audit_job["results"].append({"id": target["id"], "audit": {key: result.get(key) for key in
                        ("reachability", "score", "grade", "checked_at", "requested_url", "final_url", "http_status", "message", "audit_version")}})
                    self.audit_job["pending_targets"] = [t for t in self.audit_job.get("pending_targets", []) if t["id"] != target["id"]]
                    atomic_json(self.audit_job_file, self.audit_job)
                # Single-worker batches also limit load across repeated businesses/domains.
                if self.audit_cancel.wait(1):
                    break
            with self.lock:
                cancelled = self.audit_cancel.is_set()
                self.audit_job.update(status="cancelled" if cancelled else "complete", current_name=None,
                                      message=f"{'Stopped' if cancelled else 'Finished'} · {self.audit_job['completed']} websites checked",
                                      finished_at=timestamp())
                atomic_json(self.audit_job_file, self.audit_job)
        except Exception as exc:
            with self.lock:
                self.audit_job.update(status="failed", message="Website analysis stopped. Completed results are saved.",
                                      error=str(exc)[:1000], finished_at=timestamp())
                atomic_json(self.audit_job_file, self.audit_job)

    def resume_audits(self):
        with self.lock:
            if self.audit_job["status"] == "running" or self.research_job["status"] == "running" or getattr(self, 'rendered_running', False) or getattr(self, 'extra_active', None):
                raise ValueError("A website/research batch is already running")
            targets = self.audit_job.get("pending_targets", [])
            if not targets:
                raise ValueError("No unfinished audit tasks to resume")
            if any(t["id"] not in self.by_id for t in targets):
                raise ValueError("An unfinished target is absent from the current dataset; start a reviewed batch")
            self.audit_cancel.clear()
            self.audit_job.update(status="running", message="Resuming unfinished audits")
            atomic_json(self.audit_job_file, self.audit_job)
        threading.Thread(target=self._run_audits, args=(targets.copy(),), daemon=True).start()
        return self.audit_status()

    def _run_job(self, mode):
        staging = self.directory / "jobs" / secrets.token_hex(8)
        try:
            staging.mkdir(parents=True)
            with self.lock:
                self.job['staging'] = str(staging.relative_to(self.directory))
                atomic_json(self.collection_job_file, self.job)
            command = [sys.executable, str(ROOT / "collect_osm.py"), "--output", str(staging)]
            if mode == "clean":
                active = load_document(self.directory / "active_dataset.json", {})
                source_root = self.directory / active.get("relative_path", "")
                command += ["--input", str(source_root / "raw" / "businesses.json")]
            elif mode == "refresh":
                command += ["--refresh"]
            elif (self.directory / "cache").exists():
                shutil.copytree(self.directory / "cache", staging / "cache")
            command.insert(1, "-u")
            if os.getenv("VICALL_OVERPASS_ENDPOINT"):
                command += ["--endpoint", os.environ["VICALL_OVERPASS_ENDPOINT"]]
            log_file = staging / "collection.log"
            finished = threading.Event()
            def report_progress():
                while not finished.wait(0.5):
                    try:
                        text = log_file.read_text(encoding="utf-8", errors="replace")[-12000:]
                    except OSError:
                        continue
                    with self.lock:
                        if text != self.job.get('log'):
                            self.job["log"] = text
                            atomic_json(self.collection_job_file, self.job)
            watcher = threading.Thread(target=report_progress, daemon=True)
            watcher.start()
            try:
                with log_file.open("w", encoding="utf-8") as output:
                    result = self._execute_collector(command, output)
                log = (log_file.read_text(encoding="utf-8", errors="replace") + (result.stdout or "") + "\n" + (result.stderr or "")).strip()
            finally:
                finished.set()
                watcher.join(timeout=2)
            if result.returncode:
                raise RuntimeError(log[-4000:] or "Collector stopped without a result")
            if self.collection_cancel.is_set():
                raise CollectionCancelled('Collection cancelled before publication')
            # Save the previous snapshot before publishing the completed job.
            existing = [self.directory / folder for folder in ("raw", "processed") if (self.directory / folder).exists()]
            if existing:
                archive = self.directory / "snapshots" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
                for path in existing:
                    shutil.copytree(path, archive / path.name)
                if not load_document(self.directory / "active_dataset.json", {}):
                    atomic_json(self.directory / "active_dataset.json", {"relative_path": str(archive.relative_to(self.directory)), "published_at": timestamp()})
            else:
                empty = self.directory / "datasets" / "empty"
                empty.mkdir(parents=True, exist_ok=True)
                if not load_document(self.directory / "active_dataset.json", {}):
                    atomic_json(self.directory / "active_dataset.json", {"relative_path": str(empty.relative_to(self.directory)), "published_at": timestamp()})
            with self.lock:
                for path in staging.rglob("*"):
                    if path.is_file():
                        target = self.directory / path.relative_to(staging)
                        target.parent.mkdir(parents=True, exist_ok=True)
                        temporary = target.with_name(target.name + ".jobtmp")
                        shutil.copyfile(path, temporary)
                        os.replace(temporary, target)
                # Readers switch to one complete version. Compatibility copies
                # above are not the active dataset and may fail independently.
                candidate_rows = [json.loads(line) for line in (staging / "processed" / "businesses.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
                if any(not isinstance(r, dict) or not r.get("_id") or not r.get("name") for r in candidate_rows) or len({r["_id"] for r in candidate_rows}) != len(candidate_rows):
                    raise ValueError("Collected snapshot failed validation")
                json.loads((staging / "processed" / "quality_report.json").read_text(encoding="utf-8"))
                atomic_json(self.directory / "active_dataset.json", {"relative_path": str(staging.relative_to(self.directory)), "published_at": timestamp()})
                self.reload()
                if self.load_error:
                    raise RuntimeError(self.load_error)
                self.job.update(status="complete", message=f"Ready · {len(self.rows):,} business candidates", log=log[-12000:], finished_at=timestamp())
                atomic_json(self.collection_job_file, self.job)
        except Exception as exc:
            with self.lock:
                detail = "Collection timed out after 10 minutes. Try again later or use a saved collection." if isinstance(exc, subprocess.TimeoutExpired) else str(exc)
                self.job.update(status='cancelled' if isinstance(exc, CollectionCancelled) else "failed", message='Collection stopped. Your saved directory remains available.' if isinstance(exc, CollectionCancelled) else "Collection failed. Your current directory and notes remain available.",
                                log=(self.job.get("log", "") + "\n" + detail)[-12000:], finished_at=timestamp())
                atomic_json(self.collection_job_file, self.job)


class Handler(BaseHTTPRequestHandler):
    server_version = "VicallLocal/1.0"

    def log_message(self, *args):
        pass

    def respond(self, status, payload, content_type="application/json; charset=utf-8", filename=None):
        if not isinstance(payload, bytes):
            payload = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
        if filename:
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.end_headers()
        self.wfile.write(payload)

    def permitted(self, api=False):
        hosts = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
        if self.headers.get("Host") not in hosts:
            self.respond(403, {"error": "Only local application requests are accepted"})
            return False
        origin = self.headers.get("Origin")
        if origin and origin not in {f"http://{host}" for host in hosts}:
            self.respond(403, {"error": "Cross-origin requests are not accepted"})
            return False
        supplied = self.headers.get("X-Vicall-Token", "")
        agent = getattr(self.server, "agent_token", "")
        authorized = secrets.compare_digest(supplied, self.server.token) or bool(agent and secrets.compare_digest(self.headers.get("Authorization", ""), "Bearer "+agent))
        if api and not authorized:
            self.respond(403, {"error": "Reload the app to reconnect"})
            return False
        return True

    def do_GET(self):
        path = urlsplit(self.path).path
        if not self.permitted(api=path.startswith("/api/")):
            return
        if path == "/api/data":
            self.respond(200, self.server.workspace.data())
        elif path == "/api/job":
            self.respond(200, self.server.workspace.job_status())
        elif path == "/api/audit-job":
            self.respond(200, self.server.workspace.audit_status())
        elif path == "/api/research":
            self.respond(200, self.server.workspace.research_status())
        elif path == "/api/intelligence":
            self.respond(200, self.server.workspace.intelligence_status())
        elif path == '/api/settings':
            from app_settings import status
            self.respond(200, status(self.server.workspace))
        elif path == "/api/rendered-report":
            identity = parse_qs(urlsplit(self.path).query).get("id", [""])[0]
            from rendered_audit import rendered_report
            self.respond(200, rendered_report(self.server.workspace, identity))
        elif path in {'/api/link-report', '/api/performance-report', '/api/field-report'}:
            identity = parse_qs(urlsplit(self.path).query).get('id', [''])[0]
            try:
                self.respond(200, self.server.workspace.extended_report(identity, {'/api/link-report': 'links', '/api/performance-report': 'performance', '/api/field-report': 'field'}[path]))
            except KeyError:
                self.respond(404, {'error': 'Business not found'})
        elif path == "/api/business":
            identity = parse_qs(urlsplit(self.path).query).get("id", [""])[0]
            try:
                self.respond(200, self.server.workspace.intelligence_detail(identity))
            except KeyError:
                self.respond(404, {"error": "Business not found"})
        elif path == "/api/search":
            params = {k: v[0] for k, v in parse_qs(urlsplit(self.path).query).items()}
            try:
                if "limit" in params:
                    params["limit"] = int(params["limit"])
                for key in ("require_contact", "require_decision_maker", "require_website_issue"):
                    if key in params:
                        if params[key] not in {"true", "false"}:
                            raise ValueError(key+" must be true or false")
                        params[key] = params[key] == "true"
                self.respond(200, self.server.workspace.search_businesses(params))
            except (ValueError, TypeError) as exc:
                self.respond(400, {"error": str(exc)})
        elif path == "/api/openapi.json":
            self.respond(200, json.loads((ROOT / "docs" / "openapi.json").read_text(encoding="utf-8")))
        elif path == "/api/audit-report":
            identity = parse_qs(urlsplit(self.path).query).get("id", [""])[0]
            try:
                self.respond(200, self.server.workspace.audit_report(identity))
            except KeyError:
                self.respond(404, {"error": "Business not found"})
        elif path in {"/", "/styles.css", "/directory.css", "/ui.js", "/audit-ui.js", "/research-ui.js", "/intelligence-ui.js", "/product-ui.js", "/settings-ui.js"}:
            filename = {"/": "index.html", "/styles.css": "styles.css", "/directory.css": "directory.css", "/ui.js": "ui.js", "/audit-ui.js": "audit-ui.js", "/research-ui.js": "research-ui.js", "/intelligence-ui.js": "intelligence-ui.js", "/product-ui.js": "product-ui.js", "/settings-ui.js": "settings-ui.js"}[path]
            content = (ROOT / "ui" / filename).read_text(encoding="utf-8")
            if path == "/":
                content = content.replace("__APP_TOKEN__", self.server.token)
            mime = "text/html" if path == "/" else "text/css" if path.endswith(".css") else "text/javascript"
            self.respond(200, content.encode("utf-8"), mime + "; charset=utf-8")
        else:
            self.respond(404, {"error": "Not found"})

    def do_POST(self):
        if not self.permitted(api=True):
            return
        try:
            if self.headers.get_content_type() != "application/json":
                raise ValueError("Expected JSON")
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 2_000_000:
                raise ValueError("Request is empty or too large")
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict):
                raise ValueError("Expected a JSON object")
            path = urlsplit(self.path).path
            if path == "/api/workflow":
                self.respond(200, self.server.workspace.update(payload))
            elif path == "/api/ask":
                self.respond(200, self.server.workspace.answer_question(payload))
            elif path == '/api/settings':
                from app_settings import save
                self.respond(200, save(self.server.workspace, payload))
            elif path == "/api/matching-settings":
                self.respond(200, self.server.workspace.configure_matching(payload))
            elif path == "/api/search":
                self.respond(200, self.server.workspace.search_businesses(payload))
            elif path == "/api/organization":
                self.respond(200, self.server.workspace.save_organization(payload))
            elif path == "/api/person":
                self.respond(200, self.server.workspace.save_person(payload))
            elif path == "/api/person-delete":
                self.respond(200, self.server.workspace.delete_person(payload))
            elif path == "/api/saved-search":
                self.respond(200, self.server.workspace.save_search(payload))
            elif path == "/api/saved-search-delete":
                self.respond(200, self.server.workspace.delete_search(payload))
            elif path == "/api/research-resume":
                self.respond(202, self.server.workspace.resume_research())
            elif path == "/api/audit-resume":
                self.respond(202, self.server.workspace.resume_audits())
            elif path == "/api/backup":
                self.respond(200, self.server.workspace.backup_workspace())
            elif path == "/api/rendered-audit":
                self.respond(202, self.server.workspace.start_rendered_audit(payload))
            elif path in {'/api/link-audit', '/api/performance-audit', '/api/field-audit'}:
                self.respond(202, self.server.workspace.start_extended_audit(payload, {'/api/link-audit': 'links', '/api/performance-audit': 'performance', '/api/field-audit': 'field'}[path]))
            elif path == "/api/collect":
                self.respond(202, self.server.workspace.start_job(payload.get("mode")))
            elif path == '/api/collect-cancel':
                self.respond(200, self.server.workspace.cancel_collection())
            elif path == '/api/collect-resume':
                self.respond(202, self.server.workspace.resume_collection())
            elif path == "/api/audit":
                self.respond(202, self.server.workspace.start_audits(payload))
            elif path == "/api/audit-cancel":
                self.respond(200, self.server.workspace.cancel_audits())
            elif path == "/api/research":
                self.respond(202, self.server.workspace.start_research(payload))
            elif path == "/api/research-cancel":
                self.respond(200, self.server.workspace.cancel_research())
            elif path == "/api/research-settings":
                self.respond(200, self.server.workspace.configure_research(payload))
            elif path == "/api/discovery-add":
                self.respond(200, self.server.workspace.add_candidate(payload))
            elif path == "/api/discovery-import":
                self.respond(200, self.server.workspace.import_candidates(payload))
            elif path == "/api/target-catalog":
                self.respond(200, self.server.workspace.import_target_catalog())
            elif path == "/api/discovery-review":
                self.respond(200, self.server.workspace.review_candidate(payload))
            elif path == "/api/export":
                content = self.server.workspace.export_csv(payload.get("ids"))
                self.respond(200, content, "text/csv; charset=utf-8", "vicall-businesses.csv")
            else:
                self.respond(404, {"error": "Not found"})
        except (ValueError, TypeError) as exc:
            self.respond(400, {"error": str(exc)})
        except KeyError as exc:
            self.respond(404, {"error": str(exc)})
        except OSError:
            self.respond(500, {"error": "Could not save to disk. Check folder permissions and try again."})
        except Exception:
            logging.exception("Application request failed at %s", urlsplit(self.path).path)
            self.respond(500, {"error": "The application could not complete this request. Check the launcher log for details."})


def make_server(directory, port=8765):
    directory = Path(directory).resolve()
    handle = lock_workspace(directory)
    server = None
    try:
        workspace = Workspace(directory)
        server = LocalServer(("127.0.0.1", port), Handler)
        server.workspace_lock = handle
        server.workspace = workspace
        server.token = secrets.token_urlsafe(32)
        server.agent_token = os.getenv("VICALL_API_TOKEN", "")
        atomic_json(directory / ".app-instance.json", {"port": server.server_port})
        return server
    except Exception:
        if server:
            server.server_close()
        handle.close()
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument('--local-ai-test', action='store_true', help='Allow the optional portable local-model experiment for this launch only')
    args = parser.parse_args()
    try:
        server = make_server(args.data_dir, args.port)
    except AppAlreadyRunning as exc:
        print(str(exc) + (f" at {exc.url}" if exc.url else "."))
        if exc.url and not args.no_browser:
            webbrowser.open(exc.url)
        return 0
    except (OSError, ValueError) as exc:
        print(f"Cannot start Vicall: {exc}\nIf the port is in use, run: python app.py --port 8766", file=sys.stderr)
        return 1
    url = f"http://127.0.0.1:{server.server_port}"
    server.workspace.local_ai_test_enabled = args.local_ai_test
    print(f"Vicall is ready at {url}\nKeep this process running. Press Ctrl+C to stop.", flush=True)
    server.workspace.start_automation()
    if not args.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
