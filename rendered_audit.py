"""Optional Playwright rendering; all HTTP resources use the vetted fetcher."""
import base64
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import threading
from pathlib import Path

from storage import load_document, save_document, stamp
from website_audit import clean_url, origin

bundled = Path(__file__).parent / ".browser-deps"
if bundled.is_dir():
    sys.path.insert(0, str(bundled))


def report_path(workspace, identity):
    key = hashlib.sha256(str(identity).encode()).hexdigest()
    directory = workspace.directory / "rendered"
    directory.mkdir(exist_ok=True)
    return directory / (key + ".json")


def rendered_report(workspace, identity):
    result = load_document(report_path(workspace, identity), {"status": "not_run", "message": "No rendered audit yet"})
    if result.get("status") == "running" and not getattr(workspace, "rendered_running", False):
        result.update(status="interrupted", message="Rendered audit interrupted; start a new check")
    return result


def start_rendered(workspace, payload):
    if importlib.util.find_spec("playwright") is None:
        raise ValueError("Install requirements-browser.txt and run python -m playwright install chromium to enable rendered audits")
    identity = payload.get("id")
    if identity not in workspace.by_id:
        raise KeyError("Business not found")
    url = clean_url(payload.get("url", ""))
    with workspace.lock:
        if getattr(workspace, "rendered_running", False) or getattr(workspace, 'extra_active', None) or workspace.audit_job['status'] == 'running' or workspace.research_job['status'] == 'running':
            raise ValueError("Wait for the current website research or audit to finish")
        workspace.rendered_running = True
        result = {"status": "running", "requested_url": url, "checked_at": stamp(), "message": "Rendering bounded public resources"}
        save_document(report_path(workspace, identity), result)

    def run():
        try:
            process = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--worker", url],
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if process.returncode:
                raise ValueError("Rendered worker failed. Ensure Chromium is installed; consult the worker output locally.")
            result = json.loads(process.stdout)
        except Exception as exc:
            result = {"status": "failed", "requested_url": url, "checked_at": stamp(), "message": str(exc)[:300]}
        finally:
            with workspace.lock:
                save_document(report_path(workspace, identity), result)
                workspace.rendered_running = False
    threading.Thread(target=run, daemon=True).start()
    return result


def render(url):
    from playwright.sync_api import sync_playwright
    from business_research import ResearchCrawler
    crawler = ResearchCrawler()
    crawler.fetcher.deadline_seconds = 120
    crawler.fetcher.reset_budget()
    homepage = crawler.page(clean_url(url))
    if homepage["status"] != 200 or homepage["truncated"] or "html" not in homepage["headers"].get("content-type", ""):
        raise ValueError("Homepage is blocked, truncated, or not HTML")
    allowed_origin = origin(homepage["url"])
    cache = {homepage["url"]: homepage}
    blocked, count = [], 0
    result = {"status": "complete", "requested_url": url, "final_url": homepage["url"], "checked_at": stamp(), "viewports": [],
              "message": "Browser-rendered checks with same-origin GET resources only; third-party resources are omitted. Proxy timings are not Core Web Vitals or Lighthouse scores."}
    with sync_playwright() as p:
        channel = os.getenv("VICALL_BROWSER_CHANNEL")
        if not channel and not Path(p.chromium.executable_path).exists() and os.name == "nt":
            channel = "msedge"
        browser = p.chromium.launch(headless=True, **({"channel": channel} if channel else {}))
        try:
            context = browser.new_context(service_workers="block", accept_downloads=False)
            def route(request_route):
                nonlocal count
                request = request_route.request
                try:
                    target = clean_url(request.url)
                    if request.method != "GET" or origin(target) != allowed_origin or count >= 60:
                        raise ValueError("Outside bounded same-origin GET resource policy")
                    if target not in cache:
                        count += 1
                        fetched = crawler.fetcher.get(target, before_request=crawler.guard)
                        if fetched["truncated"] or origin(fetched["url"]) != allowed_origin:
                            raise ValueError("Resource incomplete or redirected outside origin")
                        cache[target] = fetched
                    fetched = cache[target]
                    # Encoded content has already been decompressed by the fetcher.
                    headers = {k: v for k, v in fetched["headers"].items() if k in {"content-type", "cache-control"}}
                    request_route.fulfill(status=fetched["status"], headers=headers, body=fetched["body"])
                except Exception:
                    blocked.append(request.url[:300])
                    request_route.abort()
            context.route("**/*", route)
            page = context.new_page()
            # WebSockets bypass HTTP routes; abort them explicitly.
            page.route_web_socket("**/*", lambda ws: ws.close())
            for name, width, height in (("Desktop", 1365, 900), ("Mobile", 390, 844)):
                page.set_viewport_size({"width": width, "height": height})
                page.goto(homepage["url"], wait_until="domcontentloaded", timeout=120000)
                page.wait_for_timeout(500)
                metrics = page.evaluate("""() => ({
                    title: document.title, horizontal_overflow: document.documentElement.scrollWidth > innerWidth + 2,
                    missing_alt: [...document.images].filter(i => !i.hasAttribute('alt')).length,
                    unlabeled_controls: [...document.querySelectorAll('input:not([type=hidden]),select,textarea')].filter(e => !e.labels?.length && !e.getAttribute('aria-label') && !e.getAttribute('aria-labelledby')).length,
                    h1_count: document.querySelectorAll('h1').length,
                    text_excerpt: document.body.innerText.slice(0,5000)
                })""")
                metrics.update(name=name, width=width, height=height,
                    screenshot_base64=base64.b64encode(page.screenshot(type="png", full_page=False, timeout=15000)).decode())
                result["viewports"].append(metrics)
            result["blocked_resource_count"] = len(blocked)
            result["blocked_resource_sample"] = list(dict.fromkeys(blocked))[:20]
            result["external_resource_fetches"] = count + 1
        finally:
            browser.close()
    return result


if __name__ == "__main__":
    try:
        result = render(sys.argv[2])
    except Exception as exc:
        result = {"status": "failed", "message": str(exc)[:300], "checked_at": stamp()}
    if "--output" in sys.argv:
        destination = Path(sys.argv[sys.argv.index("--output")+1])
        destination.write_text(json.dumps(result), encoding="utf-8")
        print(json.dumps({"status": result["status"], "message": result.get("message"), "viewports": len(result.get("viewports", []))}))
    else:
        print(json.dumps(result))
