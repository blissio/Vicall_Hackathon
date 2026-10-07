"""A bounded public-website audit, using only the Python standard library.

The score measures a documented set of static HTML checks, not search rankings.
"""
import gzip
import http.client
import io
import ipaddress
import json
import re
import socket
import ssl
import time
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit, urlunsplit
from xml.etree import ElementTree

AGENT = "VicallSiteAudit/1.0"
MAX_HTML = 2 * 1024 * 1024
VERSION = "1.0"


class RestrictedTarget(ValueError):
    pass


class RobotsDenied(Exception):
    pass


def clean_url(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 2048:
        raise RestrictedTarget("Enter a public website URL, up to 2,048 characters")
    value = value.strip()
    if any(c.isspace() or ord(c) < 32 for c in value) or "\\" in value:
        raise RestrictedTarget("The URL contains whitespace or invalid characters")
    if "://" not in value:
        value = "https://" + value
    try:
        parts = urlsplit(value)
        if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username or parts.password:
            raise RestrictedTarget("Use an HTTP or HTTPS URL without embedded credentials")
        host = parts.hostname.encode("idna").decode("ascii").lower().rstrip(".")
        port = parts.port
        expected = 443 if parts.scheme == "https" else 80
        if port not in {None, expected}:
            raise RestrictedTarget("Only standard public HTTP/HTTPS ports are supported")
        if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
            raise RestrictedTarget("Local and private-network websites cannot be audited")
        try:
            address = ipaddress.ip_address(host)
            if not address.is_global or address.is_multicast:
                raise RestrictedTarget("Local and private-network addresses cannot be audited")
        except ValueError as exc:
            if isinstance(exc, RestrictedTarget):
                raise
        authority = f"[{host}]" if ":" in host else host
        return urlunsplit((parts.scheme, authority, parts.path or "/", parts.query, ""))
    except (UnicodeError, ValueError) as exc:
        if isinstance(exc, RestrictedTarget):
            raise
        raise RestrictedTarget("The website URL is invalid") from exc


def public_address(host, port):
    candidates = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    if not candidates:
        raise socket.gaierror("No DNS addresses returned")
    for _, _, _, _, target in candidates:
        address = ipaddress.ip_address(target[0].split("%", 1)[0])
        if not address.is_global or address.is_multicast or (address.version == 6 and address.ipv4_mapped and not address.ipv4_mapped.is_global):
            raise RestrictedTarget("DNS resolved to a non-public address; request blocked")
    # Prefer IPv4 where available. The connection uses this vetted IP, not a second DNS lookup.
    candidates.sort(key=lambda item: item[0] != socket.AF_INET)
    return candidates[0][4][0]


class PinnedHTTP(http.client.HTTPConnection):
    def __init__(self, host, port, address, timeout):
        super().__init__(host, port, timeout=timeout)
        self.address = address

    def connect(self):
        self.sock = socket.create_connection((self.address, self.port), self.timeout)


class PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self, host, port, address, timeout):
        super().__init__(host, port, timeout=timeout, context=ssl.create_default_context())
        self.address = address

    def connect(self):
        sock = socket.create_connection((self.address, self.port), self.timeout)
        try:
            self.sock = self._context.wrap_socket(sock, server_hostname=self.host)
        except Exception:
            sock.close()
            raise


def origin(url):
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"


class PublicFetcher:
    def __init__(self, deadline_seconds=45):
        self.deadline_seconds = deadline_seconds
        self.reset_budget()
        self.last_requests = {}
        self.delays = {}

    def reset_budget(self):
        self.deadline = time.monotonic() + self.deadline_seconds

    def get(self, url, limit=MAX_HTML, before_request=None):
        request_seconds = 0
        redirects = []
        for _ in range(6):
            url = clean_url(url)
            if before_request:
                before_request(url)
            parts = urlsplit(url)
            host_origin = origin(url)
            delay = self.delays.get(host_origin, 1.0)
            wait = delay - (time.monotonic() - self.last_requests.get(host_origin, 0))
            if wait > 0:
                if time.monotonic() + wait >= self.deadline:
                    raise TimeoutError("Audit time budget exhausted while respecting request spacing")
                time.sleep(wait)
            remaining = self.deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Audit time budget exhausted")
            port = 443 if parts.scheme == "https" else 80
            request_started = time.monotonic()
            address = public_address(parts.hostname, port)
            connection_type = PinnedHTTPS if parts.scheme == "https" else PinnedHTTP
            connection = connection_type(parts.hostname, port, address, min(10, remaining))
            try:
                self.last_requests[host_origin] = time.monotonic()
                connection.request("GET", urlunsplit(("", "", parts.path or "/", parts.query, "")),
                                   headers={"User-Agent": AGENT, "Accept": "text/html,application/xhtml+xml,application/xml,text/plain;q=0.8,*/*;q=0.1", "Accept-Encoding": "identity", "Connection": "close"})
                response = connection.getresponse()
                headers = {}
                for name, value in response.getheaders():
                    name = name.lower()
                    headers[name] = headers[name] + "\n" + value if name == "x-robots-tag" and name in headers else value
                if response.status in {301, 302, 303, 307, 308}:
                    destination = headers.get("location")
                    if not destination:
                        raise ValueError("Redirect response has no destination")
                    next_url = clean_url(urljoin(url, destination))
                    if next_url == url or any(r["from"] == next_url for r in redirects):
                        raise ValueError("Redirect loop detected")
                    redirects.append({"from": url, "to": next_url, "status": response.status})
                    url = next_url
                    continue
                chunks = []
                size = 0
                while size <= limit:
                    remaining = self.deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError("Audit time budget exhausted reading the page")
                    if connection.sock:
                        connection.sock.settimeout(min(10, remaining))
                    chunk = response.read1(min(65536, limit + 1 - size))
                    if not chunk:
                        break
                    chunks.append(chunk)
                    size += len(chunk)
                content = b"".join(chunks)
                truncated = len(content) > limit
                if headers.get("content-encoding", "").lower() == "gzip":
                    with gzip.GzipFile(fileobj=io.BytesIO(content)) as packed:
                        content = packed.read(limit + 1)
                    truncated = truncated or len(content) > limit
                elif headers.get("content-encoding", "identity").lower() not in {"identity", ""}:
                    raise ValueError("Server returned an unsupported content encoding")
                match = re.search(r"charset\s*=\s*[\"']?([^;\s\"']+)", headers.get("content-type", ""), re.I)
                charset = match.group(1) if match else "utf-8"
                try:
                    text = content[:limit].decode(charset, errors="replace")
                except LookupError:
                    text = content[:limit].decode("utf-8", errors="replace")
                return {"url": url, "status": response.status, "headers": headers, "text": text,
                        "bytes_read": min(len(content), limit), "truncated": truncated,
                        "redirects": redirects, "fetch_ms": round((request_seconds + time.monotonic() - request_started) * 1000)}
            finally:
                request_seconds += time.monotonic() - request_started
                connection.close()
        raise ValueError("Too many redirects (maximum five)")


def robots_policy(text, agent, url):
    """Common robots group, wildcard and Allow precedence rules; not an index test."""
    groups = []
    agents, rules, delay = [], [], None
    directives_seen = False
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if ":" not in line:
            continue
        key, value = (s.strip() for s in line.split(":", 1))
        key = key.lower()
        if key == "user-agent":
            if directives_seen:
                groups.append((agents, rules, delay))
                agents, rules, delay = [], [], None
                directives_seen = False
            agents.append(value.lower())
        elif key in {"allow", "disallow"} and agents:
            directives_seen = True
            if value:
                rules.append((key, value))
        elif key == "crawl-delay" and agents:
            directives_seen = True
            try:
                delay = max(0, float(value))
            except ValueError:
                pass
    groups.append((agents, rules, delay))
    matching = []
    for names, directives, group_delay in groups:
        scores = [0 if name == "*" else len(name) for name in names if name == "*" or name in agent.lower()]
        if scores:
            matching.append((max(scores), directives, group_delay))
    if not matching:
        return {"allowed": True, "matched_rule": None, "crawl_delay": 1.0}
    specificity = max(item[0] for item in matching)
    path = urlsplit(url).path or "/"
    if urlsplit(url).query:
        path += "?" + urlsplit(url).query
    matches = []
    delays = [1.0]
    for score, directives, group_delay in matching:
        if score != specificity:
            continue
        if group_delay is not None:
            delays.append(group_delay)
        for key, value in directives:
            anchored = value.endswith("$")
            expression = re.escape(value[:-1] if anchored else value).replace(r"\*", ".*")
            if re.match("^" + expression + ("$" if anchored else ""), path):
                matches.append((len(value.replace("*", "").rstrip("$")), key == "allow", f"{key}: {value}"))
    selected = max(matches) if matches else None
    return {"allowed": selected[1] if selected else True,
            "matched_rule": selected[2] if selected else None, "crawl_delay": max(delays)}


class PageParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.title = []
        self.h1 = []
        self.meta = {}
        self.canonicals = []
        self.links = []
        self.images = []
        self.json_ld = []
        self.script_count = 0
        self.structured_current = None
        self.text = []

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        attrs = dict(attrs)
        if tag not in {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}:
            self.stack.append(tag)
        if tag == "h1":
            self.h1.append([])
        if tag == "meta":
            key = (attrs.get("name") or attrs.get("property") or "").lower()
            self.meta.setdefault(key, []).append(attrs.get("content") or "")
        if tag == "link" and "canonical" in (attrs.get("rel") or "").lower().split():
            self.canonicals.append(attrs.get("href") or "")
        if tag == "a":
            self.links.append(attrs.get("href") or "")
        if tag == "img":
            self.images.append({"alt_present": "alt" in attrs, "alt": attrs.get("alt") or ""})
        if tag == "script" and (attrs.get("type") or "").lower() == "application/ld+json":
            self.structured_current = []
        if tag == "script":
            self.script_count += 1

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag in self.stack:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if tag == "script" and self.structured_current is not None:
            self.json_ld.append("".join(self.structured_current))
            self.structured_current = None
        if tag in self.stack:
            self.stack = self.stack[:len(self.stack) - 1 - self.stack[::-1].index(tag)]

    def handle_data(self, data):
        if "title" in self.stack:
            self.title.append(data)
        if "h1" in self.stack and self.h1:
            self.h1[-1].append(data)
        if self.structured_current is not None:
            self.structured_current.append(data)
        if not any(tag in self.stack for tag in ("script", "style", "noscript", "title")):
            self.text.append(data)


def inspect_page(page, google_allowed=None):
    parser = PageParser()
    parser.feed(page["text"])
    title = " ".join("".join(parser.title).split())
    description = next((v.strip() for v in parser.meta.get("description", []) if v.strip()), "")
    headings = [" ".join("".join(parts).split()) for parts in parser.h1]
    directives = re.split(r"[\s,;]+", " ".join([*parser.meta.get("robots", []), *parser.meta.get("googlebot", [])]).lower())
    # Header lines can scope rules to a crawler. Colon-valued directives are not agent names.
    valued_directives = {"max-snippet", "max-image-preview", "max-video-preview", "unavailable_after"}
    for line in page["headers"].get("x-robots-tag", "").splitlines():
        scope = None
        for part in line.lower().split(","):
            match = re.match(r"\s*([\w-]+)\s*:\s*(.*)", part)
            if match and match.group(1) not in valued_directives:
                scope = match.group(1)
                part = match.group(2)
            if scope in {None, "googlebot", "robots"}:
                directives += re.split(r"[\s,;]+", part)
    noindex = bool({"noindex", "none"} & set(directives))
    canonicals = [urljoin(page["url"], href) for href in parser.canonicals if href]
    usable_canonical = len(canonicals) == 1 and urlsplit(canonicals[0]).scheme in {"http", "https"}
    viewport = any("width=device-width" in v.lower().replace(" ", "") for v in parser.meta.get("viewport", []))
    image_missing = sum(not img["alt_present"] for img in parser.images)
    internal = {urljoin(page["url"], href).split("#", 1)[0] for href in parser.links if href and not href.startswith("#")
                and urlsplit(urljoin(page["url"], href)).scheme in {"http", "https"}
                and origin(urljoin(page["url"], href)) == origin(page["url"])}
    internal.discard(page["url"].split("#", 1)[0])
    structured_types = set()
    invalid_json = 0

    def walk(value):
        if isinstance(value, dict):
            kind = value.get("@type", [])
            structured_types.update([kind] if isinstance(kind, str) else [v for v in kind if isinstance(v, str)] if isinstance(kind, list) else [])
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    for payload in parser.json_ld:
        try:
            walk(json.loads(payload))
        except (ValueError, RecursionError):
            invalid_json += 1
    checks = []

    def check(key, label, passed, weight, evidence, fix, severity="warning"):
        checks.append({"key": key, "label": label, "status": "pass" if passed else severity,
                       "weight": weight, "evidence": evidence, "recommendation": "No change suggested by this check." if passed else fix})

    check("https", "HTTPS", page["url"].startswith("https://"), 10, page["url"], "Serve the page through HTTPS and redirect HTTP traffic.")
    check("title", "Page title present", bool(title), 20, title[:300] or "No non-empty <title> found.", "Add a unique, descriptive title identifying the business and page.")
    check("description", "Meta description", bool(description), 15, description[:400] or "No non-empty description found.", "Write a useful page summary for potential visitors. Google may choose a different snippet.")
    check("h1", "Main heading", any(headings), 15, f"{len(headings)} H1 elements: " + "; ".join(headings)[:300], "Add a visible main heading explaining the page. Verify rendered content before editing.")
    check("viewport", "Mobile viewport declaration", viewport, 10, "; ".join(parser.meta.get("viewport", [])) or "No viewport declaration found.", "Add width=device-width and test the actual mobile layout.")
    check("indexing", "No observed indexing blocker", not noindex and google_allowed is not False, 15,
          ("Observed noindex/none directive." if noindex else "Googlebot appears disallowed for this path." if google_allowed is False else "No noindex found; crawler rules could not be confirmed." if google_allowed is None else "No noindex found; sampled robots rules allow Googlebot."),
          "Confirm whether this page should appear in search. Remove accidental indexing/crawling restrictions only when appropriate.", "critical")
    check("canonical", "Canonical URL declaration", usable_canonical, 5, "; ".join(canonicals)[:300] or "No canonical link found.", "Review duplicate URL variants and consider one appropriate canonical URL. It is not mandatory on every page.")
    check("alt", "Image alt attributes", image_missing == 0, 5, f"{image_missing} of {len(parser.images)} images lack an alt attribute; empty alt may be valid for decoration.", "Add meaningful alt text to informative images; use empty alt for decorative images.")
    check("links", "Internal navigation links", bool(internal), 5, f"{len(internal)} distinct same-origin links in static HTML (targets not checked).", "Provide useful crawlable internal navigation; review the rendered page if navigation uses JavaScript.")
    # Unknown robots evidence receives no confident indexing points.
    if google_allowed is None and not noindex:
        checks[5]["status"] = "unknown"
        checks[5]["recommendation"] = "Recheck robots.txt before drawing an indexing conclusion."
    if page.get("truncated"):
        for item in checks:
            if item["status"] not in {"pass", "critical"}:
                item["status"] = "unknown"
                item["recommendation"] = "Page content was truncated; verify this finding in a complete rendered audit."
    for label, observed, tip in [
        ("Structured data", ", ".join(sorted(structured_types)) or "No JSON-LD types found (other formats not checked).", "Validate any relevant LocalBusiness structured data; its presence alone does not establish correctness."),
        ("Social sharing metadata", "Open Graph title found." if parser.meta.get("og:title") else "No Open Graph title found.", "Consider descriptive social sharing metadata; this is not a search ranking requirement."),
        ("Title length", f"{len(title)} characters; there is no fixed Google title-length limit.", "Review whether the title clearly describes the business without keyword stuffing.")]:
        checks.append({"key": label.lower().replace(" ", "_"), "label": label, "status": "info", "weight": 0, "evidence": observed, "recommendation": tip})
    if invalid_json:
        checks.append({"key": "json_ld_parse", "label": "JSON-LD syntax", "status": "warning", "weight": 0,
                       "evidence": f"{invalid_json} JSON-LD blocks could not be parsed.", "recommendation": "Validate and repair malformed structured-data JSON."})
    javascript_dependent = parser.script_count > 0 and len(" ".join(" ".join(parser.text).split())) < 80
    if javascript_dependent:
        for item in checks:
            if item["status"] == "warning" and item["weight"]:
                item["status"] = "unknown"
                item["recommendation"] = "Verify this signal in a browser-rendered page before recommending a change."
        checks.append({"key": "rendering", "label": "Browser-rendered audit needed", "status": "warning", "weight": 0,
                       "evidence": "Very little text was returned with scripts present; the page may depend on JavaScript.",
                       "recommendation": "Inspect this URL in a real browser before assessing missing page content."})
    possible = sum(c["weight"] for c in checks if c["status"] != "unknown")
    score = round(100 * sum(c["weight"] for c in checks if c["status"] == "pass") / possible) if possible and not page.get("truncated") and not javascript_dependent else None
    if score is not None and any(c["status"] == "critical" for c in checks):
        score = min(score, 49)
    label = "partial" if score is None else "strong" if score >= 80 else "review" if score >= 50 else "needs_work"
    return {"score": score, "grade": label, "checks": checks, "metrics": {"title": title[:500], "description": description[:700],
            "h1_count": len(headings), "image_count": len(parser.images), "missing_alt": image_missing,
            "internal_links": len(internal), "structured_types": sorted(structured_types), "body_bytes": page["bytes_read"]},
            "score_coverage": possible, "limitations": ["Static HTML of one URL; JavaScript is not rendered.",
            "Technical checklist score, not a ranking prediction or full SEO audit.", "Business/website identity has not been confirmed.",
            "Response time is a single fetch measurement, not Core Web Vitals."]}


def audit_website(url, fetcher=None):
    result = {"requested_url": url, "checked_at": datetime.now(timezone.utc).isoformat(), "audit_version": VERSION,
              "reachability": "unknown", "score": None, "grade": "unknown", "checks": [], "redirects": [],
              "http_status": None, "final_url": None, "fetch_ms": None, "recommendations": []}
    fetcher = fetcher or PublicFetcher()
    if hasattr(fetcher, "reset_budget"):
        fetcher.reset_budget()
    policies = {}

    def policy_for(target):
        host_origin = origin(target)
        if host_origin not in policies:
            robots = fetcher.get(host_origin + "/robots.txt", limit=100000)
            if robots["status"] in {401, 403, 429} or robots["status"] >= 500:
                raise RobotsDenied(f"robots.txt returned HTTP {robots['status']}; automated page fetch deferred")
            if robots["status"] == 200 and not robots["truncated"] and "<html" not in robots["text"][:1000].lower():
                policies[host_origin] = {"text": robots["text"], "url": robots["url"], "status": 200, "known": True}
            elif robots["status"] in {404, 410}:
                policies[host_origin] = {"text": "", "url": robots["url"], "status": robots["status"], "known": True}
            else:
                raise RobotsDenied("robots.txt response was incomplete or could not be interpreted; automated page fetch deferred")
        return policies[host_origin]

    def guard(target):
        policy = policy_for(target)
        rules = robots_policy(policy["text"], AGENT, target)
        fetcher.delays[origin(target)] = rules["crawl_delay"]
        if not rules["allowed"]:
            raise RobotsDenied(f"Automated fetch disallowed by robots.txt ({rules['matched_rule']})")

    try:
        target = clean_url(url)
        result["requested_url"] = target
        page = fetcher.get(target, before_request=guard)
        result.update(final_url=page["url"], http_status=page["status"], fetch_ms=page["fetch_ms"], redirects=page["redirects"])
        if page["status"] in {401, 403, 429, 503}:
            result.update(reachability="restricted", message=f"HTTP {page['status']}; access may be restricted or temporarily unavailable.")
        elif not 200 <= page["status"] < 300:
            result.update(reachability="http_error", message=f"This URL returned HTTP {page['status']}; no SEO grade assigned.")
        elif not any(mime in page["headers"].get("content-type", "").lower() for mime in ("text/html", "application/xhtml+xml")):
            result.update(reachability="non_html", message="URL responded successfully but did not return an HTML page.")
        elif any(marker in page["text"].lower() for marker in ("cf-chl-", "/cdn-cgi/challenge-platform/", "verify you are human", "checking your browser")):
            result.update(reachability="restricted", message="A bot challenge was detected; verify reachability in a normal browser.")
        else:
            policy = policy_for(page["url"])
            google = robots_policy(policy["text"], "Googlebot", page["url"])
            result.update(reachability="reachable", message="The sampled URL returned an HTML page.", robots={"url": policy["url"], "status": policy["status"], "googlebot_allowed": google["allowed"], "matched_rule": google["matched_rule"]})
            result.update(inspect_page(page, google["allowed"]))
            # Optional sitemap probe is evidence only and never changes the SEO score.
            declared = re.findall(r"^\s*Sitemap\s*:\s*(\S+)", policy["text"], re.I | re.M)
            sitemap_url = next((u for u in declared if origin(urljoin(page["url"], u)) == origin(page["url"])), origin(page["url"]) + "/sitemap.xml")
            try:
                sitemap = fetcher.get(sitemap_url, limit=256000, before_request=guard)
                valid = False
                if sitemap["status"] == 200 and not sitemap["truncated"]:
                    try:
                        document = ElementTree.fromstring(sitemap["text"])
                        valid = document.tag.split("}")[-1] in {"urlset", "sitemapindex"}
                    except (ElementTree.ParseError, ValueError):
                        pass
                result["sitemap"] = {"url": sitemap["url"], "status": sitemap["status"], "valid_xml": valid, "truncated": sitemap["truncated"]}
                evidence = "Recognized sitemap XML found." if valid else "No complete recognized sitemap found at the sampled URL; other locations may exist."
            except (OSError, ValueError, RobotsDenied) as exc:
                evidence = f"Sitemap check inconclusive: {str(exc)[:180]}"
            result["checks"].append({"key": "sitemap", "label": "Sitemap discovery", "status": "info", "weight": 0,
                                     "evidence": evidence, "recommendation": "A sitemap can aid discovery but is optional; check your CMS or Search Console."})
    except RestrictedTarget as exc:
        result.update(reachability="restricted", message=str(exc))
    except RobotsDenied as exc:
        result.update(reachability="restricted", message=str(exc))
    except socket.gaierror:
        result.update(reachability="unreachable", message="DNS lookup failed from this computer. Recheck before concluding the website is unavailable.")
    except ssl.SSLError:
        result.update(reachability="unknown", message="TLS connection or certificate validation failed. HTTPS verification is inconclusive.")
    except (TimeoutError, socket.timeout):
        result.update(reachability="unknown", message="Request timed out or exceeded the audit budget. No SEO grade assigned.")
    except (ConnectionError, OSError):
        result.update(reachability="unreachable", message="The connection failed from this computer. This is a point-in-time observation.")
    except (ValueError, http.client.HTTPException) as exc:
        result.update(reachability="unknown", message=f"Audit inconclusive: {str(exc)[:250]}")
    result["recommendations"] = [c for c in result["checks"] if c["status"] in {"warning", "critical"}]
    if not result["checks"]:
        result["recommendations"] = [{"label": "Verify the website", "recommendation": "Open the URL in a browser, confirm it belongs to the business, and retry later. A blocked or failed check is not a bad SEO score.", "status": "info", "evidence": result.get("message", "")}]
    return result
