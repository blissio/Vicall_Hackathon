"""Vicall local graphical application. Run: python app.py"""
import argparse
import csv
import io
import json
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

ROOT = Path(__file__).resolve().parent
STAGES = ("New", "Researching", "Qualified", "Not a fit")


class AppAlreadyRunning(Exception):
    def __init__(self, url):
        self.url = url
        super().__init__("This workspace is already open in Vicall")


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
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


class Workspace:
    def __init__(self, directory):
        self.directory = Path(directory).resolve()
        self.lock = threading.RLock()
        self.rows = []
        self.by_id = {}
        self.report = {}
        self.load_error = None
        self.workflow_file = self.directory / "workspace.json"
        self.workflow = {}
        if self.workflow_file.exists():
            # Never silently overwrite unreadable research notes.
            self.workflow = json.loads(self.workflow_file.read_text(encoding="utf-8"))
            if not isinstance(self.workflow, dict):
                raise ValueError("workspace.json must contain an object")
        self.job = {"status": "idle", "message": "Ready", "log": ""}
        self.audits_file = self.directory / "website_audits.json"
        self.audits = json.loads(self.audits_file.read_text(encoding="utf-8")) if self.audits_file.exists() else {}
        if not isinstance(self.audits, dict):
            raise ValueError("website_audits.json must contain an object")
        self.audit_job = {"status": "idle", "message": "Ready to analyze websites", "completed": 0, "total": 0, "skipped": 0}
        self.audit_cancel = threading.Event()
        self.reload()

    def reload(self):
        path = self.directory / "processed" / "businesses.jsonl"
        try:
            rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()] if path.exists() else []
            if any(not isinstance(r, dict) or not r.get("_id") or not r.get("name") for r in rows):
                raise ValueError("Dataset contains a record without an ID or name")
            if len({r["_id"] for r in rows}) != len(rows):
                raise ValueError("Dataset contains duplicate source IDs")
            enrich_neighborhoods(rows)
            report_path = self.directory / "processed" / "quality_report.json"
            report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else {}
            with self.lock:
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
                businesses.append(copy)
            return {"businesses": businesses, "report": self.report, "error": self.load_error, "audit_version": AUDIT_VERSION, "neighborhood_source": NEIGHBORHOOD_SOURCE,
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
        patch = {key: value for key, value in payload.items() if key in {"shortlisted", "stage", "notes"}}
        if not patch:
            raise ValueError("No research changes supplied")
        if "shortlisted" in patch and not isinstance(patch["shortlisted"], bool):
            raise ValueError("Shortlisted must be true or false")
        if "stage" in patch and patch["stage"] not in STAGES:
            raise ValueError("Unknown research stage")
        if "notes" in patch and (not isinstance(patch["notes"], str) or len(patch["notes"]) > 12000):
            raise ValueError("Notes must be text, up to 12,000 characters")
        with self.lock:
            if identity not in self.by_id:
                raise KeyError("Business no longer exists in the current dataset")
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
                  "audited_url", "website_reachability", "http_status", "technical_seo_score", "seo_grade", "audit_date", "suggested_improvements"]
        writer = csv.DictWriter(buffer, fieldnames=fields)
        writer.writeheader()
        with self.lock:
            for identity in dict.fromkeys(identities):
                if identity not in self.by_id:
                    continue
                r = self.by_id[identity]
                a, w = r.get("address", {}), self.workflow.get(identity, {})
                audit = self.audits.get(identity, {}).get("latest", {})
                row = {"name": r["name"], "category": r.get("category", ""),
                       "neighborhood": r.get("neighborhood"), "neighborhood_method": r.get("neighborhood_method"), "neighborhood_source": NEIGHBORHOOD_SOURCE,
                       "street_address": " ".join(a.get(k) or "" for k in ("house_number", "street", "unit")).strip(),
                       "city": a.get("city"), "postcode": a.get("postcode"),
                       "websites": "; ".join(r.get("websites", [])), "website_status": r.get("website_status"),
                       "phones": "; ".join(r.get("phones", [])), "emails": "; ".join(r.get("emails", [])),
                       "research_stage": w.get("stage", "New"), "shortlisted": w.get("shortlisted", False),
                       "notes": w.get("notes", ""), "source_url": r.get("source", {}).get("url", ""),
                       "attribution": "© OpenStreetMap contributors", "license_url": "https://www.openstreetmap.org/copyright",
                       "audited_url": audit.get("requested_url"), "website_reachability": audit.get("reachability"),
                       "http_status": audit.get("http_status"), "technical_seo_score": audit.get("score"),
                       "seo_grade": audit.get("grade"), "audit_date": audit.get("checked_at"),
                       "suggested_improvements": " | ".join(c.get("recommendation", "") for c in audit.get("recommendations", []))}
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
        threading.Thread(target=self._run_job, args=(mode,), daemon=True).start()
        return self.job_status()

    def job_status(self):
        with self.lock:
            return dict(self.job)

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
            if self.audit_job["status"] == "running":
                raise ValueError("A website audit is already running")
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
                                "target_source": "listed_in_osm" if url in business.get("websites", []) else "user_supplied"})
            self.audit_cancel.clear()
            self.audit_job = {"status": "running" if targets else "complete", "message": "Starting website analysis…" if targets else "No new checks needed. Missing URLs or results under 24 hours old were skipped.",
                              "completed": 0, "total": len(targets), "skipped": skipped, "started_at": timestamp(), "current_name": None,
                              "ids": [t["id"] for t in targets], "results": []}
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
                # Single-worker batches also limit load across repeated businesses/domains.
                if self.audit_cancel.wait(1):
                    break
            with self.lock:
                cancelled = self.audit_cancel.is_set()
                self.audit_job.update(status="cancelled" if cancelled else "complete", current_name=None,
                                      message=f"{'Stopped' if cancelled else 'Finished'} · {self.audit_job['completed']} websites checked",
                                      finished_at=timestamp())
        except Exception as exc:
            with self.lock:
                self.audit_job.update(status="failed", message="Website analysis stopped. Completed results are saved.",
                                      error=str(exc)[:1000], finished_at=timestamp())

    def _run_job(self, mode):
        staging = self.directory / "jobs" / secrets.token_hex(8)
        try:
            staging.mkdir(parents=True)
            command = [sys.executable, str(ROOT / "collect_osm.py"), "--output", str(staging)]
            if mode == "clean":
                command += ["--input", str(self.directory / "raw" / "businesses.json")]
            elif mode == "refresh":
                command += ["--refresh"]
            elif (self.directory / "cache").exists():
                shutil.copytree(self.directory / "cache", staging / "cache")
            result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
                                    errors="replace", env={**os.environ, "PYTHONIOENCODING": "utf-8"},
                                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            log = (result.stdout + "\n" + result.stderr).strip()
            if result.returncode:
                raise RuntimeError(log[-4000:] or "Collector stopped without a result")
            # Save the previous snapshot before publishing the completed job.
            existing = [self.directory / folder for folder in ("raw", "processed") if (self.directory / folder).exists()]
            if existing:
                archive = self.directory / "snapshots" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
                for path in existing:
                    shutil.copytree(path, archive / path.name)
            with self.lock:
                for path in staging.rglob("*"):
                    if path.is_file():
                        target = self.directory / path.relative_to(staging)
                        target.parent.mkdir(parents=True, exist_ok=True)
                        temporary = target.with_name(target.name + ".jobtmp")
                        shutil.copyfile(path, temporary)
                        os.replace(temporary, target)
                self.reload()
                if self.load_error:
                    raise RuntimeError(self.load_error)
                self.job.update(status="complete", message=f"Ready · {len(self.rows):,} business candidates", log=log[-12000:], finished_at=timestamp())
        except Exception as exc:
            with self.lock:
                self.job.update(status="failed", message="Collection failed. Your current directory and notes remain available.",
                                log=str(exc)[-12000:], finished_at=timestamp())


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
        if api and not secrets.compare_digest(self.headers.get("X-Vicall-Token", ""), self.server.token):
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
        elif path == "/api/audit-report":
            identity = parse_qs(urlsplit(self.path).query).get("id", [""])[0]
            try:
                self.respond(200, self.server.workspace.audit_report(identity))
            except KeyError:
                self.respond(404, {"error": "Business not found"})
        elif path in {"/", "/styles.css", "/ui.js", "/audit-ui.js"}:
            filename = {"/": "index.html", "/styles.css": "styles.css", "/ui.js": "ui.js", "/audit-ui.js": "audit-ui.js"}[path]
            content = (ROOT / "ui" / filename).read_text(encoding="utf-8")
            if path == "/":
                content = content.replace("__APP_TOKEN__", self.server.token)
            mime = {"/": "text/html", "/styles.css": "text/css", "/ui.js": "text/javascript", "/audit-ui.js": "text/javascript"}[path]
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
            elif path == "/api/collect":
                self.respond(202, self.server.workspace.start_job(payload.get("mode")))
            elif path == "/api/audit":
                self.respond(202, self.server.workspace.start_audits(payload))
            elif path == "/api/audit-cancel":
                self.respond(200, self.server.workspace.cancel_audits())
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
    print(f"Vicall is ready at {url}\nKeep this process running. Press Ctrl+C to stop.", flush=True)
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
