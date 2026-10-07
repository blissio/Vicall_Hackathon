"""Bounded public-website enrichment and licensed public-directory discovery."""
import hashlib
import http.client
import json
import re
from datetime import datetime, timezone
from urllib.parse import urlencode, urljoin, urlsplit, unquote

from website_audit import AGENT, PageParser, PublicFetcher, RobotsDenied, clean_url, origin, robots_policy

SOURCES = {
    "city_businesses": {"name": "Pittsburgh business licenses", "resource": "e88c10d5-541d-417f-aef6-25cc5637aeb1", "dataset": "business-contractors-trades", "fields": "license_number,license_type_name,business_name,license_state,expiration_date,most_recent_issue_date,email_address,primary_phone_number", "active": True},
    "city_contractors": {"name": "Pittsburgh licensed contractors", "resource": "7e195511-5219-4d16-84f7-f34a2aedf5b4", "dataset": "business-contractors-trades", "fields": "license_number,license_type_name,business_name,license_state,expiration_date,most_recent_issue_date", "active": True},
    "county_directory": {"name": "Allegheny County certified-business directory", "resource": "cde4503b-1e1c-4afc-9fc5-d49c1bebb4ee", "dataset": "allegheny-county-certified-mwdbe-businesses", "fields": "vendor_id,firm_name,work_description,website,phone_number,email_address", "active": False},
}
SOCIAL_HOSTS = {"facebook.com": "Facebook", "fb.com": "Facebook", "instagram.com": "Instagram", "linkedin.com": "LinkedIn", "twitter.com": "X", "x.com": "X", "tiktok.com": "TikTok", "youtube.com": "YouTube", "youtu.be": "YouTube", "wa.me": "WhatsApp", "api.whatsapp.com": "WhatsApp"}


def stamp():
    return datetime.now(timezone.utc).isoformat()


def social_platform(url):
    host = (urlsplit(url).hostname or "").lower()
    return next((name for domain, name in SOCIAL_HOSTS.items() if host == domain or host.endswith("."+domain)), None)


def normalized_name(value):
    return re.sub(r"[^a-z0-9]", "", str(value).lower())


def phone(value):
    value = unquote(str(value)).split("?", 1)[0].strip()
    digits = re.sub(r"\D", "", value)
    if re.fullmatch(r"[+\d() .-]+", value) and (len(digits) == 10 or len(digits) == 11 and digits.startswith("1")):
        return "+1" + digits[-10:]
    return None


def email(value):
    value = unquote(str(value)).split("?", 1)[0].strip().lower()
    return value if len(value) <= 254 and re.fullmatch(r"[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+", value) else None


class ContactParser(PageParser):
    def __init__(self):
        super().__init__()
        self.forms = []
        self.anchors = []
        self.anchor = None

    def handle_starttag(self, tag, attrs):
        super().handle_starttag(tag, attrs)
        attrs = dict(attrs)
        if tag == "form":
            self.forms.append(attrs.get("action") or "")
        if tag == "a":
            self.anchor = {"href": attrs.get("href") or "", "text": ""}
            self.anchors.append(self.anchor)

    def handle_data(self, data):
        super().handle_data(data)
        if self.anchor:
            self.anchor["text"] += data

    def handle_endtag(self, tag):
        super().handle_endtag(tag)
        if tag == "a":
            self.anchor = None


def extract_contacts(page, checked_at=None):
    """Explicit public contact links and organization schema, never hidden/private data."""
    checked_at = checked_at or stamp()
    parser = ContactParser()
    parser.feed(page["text"])
    claims = {}

    def add(kind, value, method):
        if not value:
            return
        claims.setdefault((kind, value), {"kind": kind, "value": value, "source_url": page["url"], "observed_at": checked_at, "method": method, "verification": "observed_not_verified"})

    for anchor in parser.anchors:
        href = anchor["href"]
        if href.lower().startswith("mailto:"):
            for address in href[7:].split("?", 1)[0].split(","):
                add("email", email(address), "Public email link")
        elif href.lower().startswith("tel:"):
            add("phone", phone(href[4:]), "Public telephone link")
        else:
            try:
                link = clean_url(urljoin(page["url"], href))
            except ValueError:
                continue
            platform = social_platform(link)
            if platform and not any(word in link.lower() for word in ("/sharer", "/share?", "/intent/", "/login")):
                add("social", link, platform + " link on sampled website")
            elif origin(link) == origin(page["url"]) and re.search(r"contact|reach.us|get.in.touch", anchor["text"] + " " + urlsplit(link).path, re.I):
                add("contact_page", link, "Contact-page link; form not submitted")
    for action in parser.forms:
        if re.search(r"contact|inquir|message", page["url"] + " " + action, re.I):
            add("contact_form", page["url"], "Form observed; deliverability not tested")

    def organizations(value):
        if isinstance(value, dict):
            types = value.get("@type", [])
            types = [types] if isinstance(types, str) else types if isinstance(types, list) else []
            # Person schema is deliberately excluded; these are business channels.
            if any(t in {"Organization", "LocalBusiness", "Restaurant", "CafeOrCoffeeShop", "Store", "ProfessionalService", "HomeAndConstructionBusiness", "Electrician", "Plumber", "Dentist", "LegalService", "Bakery"} for t in types):
                add("email", email(value.get("email", "")), "Organization structured data")
                add("phone", phone(value.get("telephone", "")), "Organization structured data")
                same = value.get("sameAs", [])
                for item in ([same] if isinstance(same, str) else same if isinstance(same, list) else []):
                    try:
                        link = clean_url(item)
                        if social_platform(link):
                            add("social", link, "Organization structured data")
                    except (ValueError, TypeError):
                        pass
            for item in value.values():
                organizations(item)
        elif isinstance(value, list):
            for item in value:
                organizations(item)
    for payload in parser.json_ld:
        try:
            organizations(json.loads(payload))
        except (ValueError, RecursionError):
            pass
    links = []
    for href in parser.links:
        try:
            link = clean_url(urljoin(page["url"], href))
        except ValueError:
            continue
        if origin(link) == origin(page["url"]) and re.search(r"contact|about|service", urlsplit(link).path, re.I):
            if link not in links and link != page["url"]:
                links.append(link)
    return list(claims.values()), links, " ".join(" ".join(parser.text).split())[:5000]


class ResearchCrawler:
    def __init__(self, fetcher=None):
        self.fetcher = fetcher or PublicFetcher(deadline_seconds=65)
        self.policies = {}

    def guard(self, url):
        if social_platform(url):
            raise RobotsDenied("Social platforms are saved as links for manual review, not automatically collected")
        host = origin(url)
        if host not in self.policies:
            robots = self.fetcher.get(host+"/robots.txt", limit=100000)
            if robots["status"] in {404, 410}:
                text = ""
            elif robots["status"] == 200 and not robots["truncated"] and "<html" not in robots["text"][:1000].lower():
                text = robots["text"]
            else:
                raise RobotsDenied("Robots rules could not be confirmed; page collection deferred")
            self.policies[host] = text
        rules = robots_policy(self.policies[host], AGENT, url)
        self.fetcher.delays[host] = rules["crawl_delay"]
        if not rules["allowed"]:
            raise RobotsDenied("Page collection disallowed by robots.txt")

    def page(self, url):
        return self.fetcher.get(url, limit=1_000_000, before_request=self.guard)


def enrich_business(business, url, crawler=None):
    result = {"checked_at": stamp(), "requested_url": clean_url(url), "contacts": [], "pages": [], "status": "inconclusive", "identity": "unverified", "identity_signals": []}
    crawler = crawler or ResearchCrawler()
    crawler.fetcher.reset_budget()
    queue, seen = [result["requested_url"]], set()
    allowed_origin = None
    for _ in range(4):
        if not queue:
            break
        target = queue.pop(0)
        if target in seen:
            continue
        seen.add(target)
        try:
            page = crawler.page(target)
            # Redirected subpages must stay within the sampled homepage origin.
            if allowed_origin and origin(page["url"]) != allowed_origin:
                raise ValueError("Subpage redirected away from the sampled business site")
            item = {"url": page["url"], "http_status": page["status"], "checked_at": result["checked_at"], "truncated": page["truncated"]}
            result["pages"].append(item)
            if not 200 <= page["status"] < 300:
                item["outcome"] = "restricted" if page["status"] in {401, 403, 429, 503} else "http_error"
                continue
            if "html" not in page["headers"].get("content-type", "").lower():
                item["outcome"] = "non_html"
                continue
            if any(m in page["text"].lower() for m in ("cf-chl-", "verify you are human", "/cdn-cgi/challenge-platform/", "checking your browser")):
                item["outcome"] = "restricted"
                continue
            allowed_origin = allowed_origin or origin(page["url"])
            claims, links, text = extract_contacts(page, result["checked_at"])
            item["outcome"] = "partial" if page["truncated"] else "html_observed"
            result["contacts"].extend(claims)
            result["status"] = "partial" if page["truncated"] else "observed"
            name = normalized_name(business.get("name", ""))
            if len(name) >= 5 and name in normalized_name(text):
                result["identity_signals"].append({"signal": "Business name appears in sampled text", "source_url": page["url"]})
            listed = set(business.get("phones", [])) | set(business.get("emails", []))
            for claim in claims:
                if claim["value"] in listed:
                    result["identity_signals"].append({"signal": "Contact matches an existing listing", "source_url": page["url"]})
            if not page["truncated"]:
                queue.extend(link for link in links if link not in seen and link not in queue)
        except (OSError, ValueError, RobotsDenied, http.client.HTTPException) as exc:
            result["pages"].append({"url": target, "checked_at": result["checked_at"], "outcome": "inconclusive", "message": str(exc)[:180]})
            if not result["contacts"]:
                result["message"] = str(exc)[:180]
    result["contacts"] = list({(c["kind"], c["value"], c["source_url"]): c for c in result["contacts"]}.values())
    result["message"] = (result.get("message") or "No readable business HTML confirmed. Review the individual page outcomes; no operation or contact conclusion inferred.") if result["status"] == "inconclusive" else f"Sampled {len(result['pages'])} pages; observed {len(result['contacts'])} contact references. Business identity and contact deliverability remain unverified."
    return result


def fetch_directory(key, fetcher=None, maximum=1000):
    spec = SOURCES[key]
    fetcher = fetcher or PublicFetcher(deadline_seconds=90)
    fetcher.reset_budget()
    records, total = [], 0
    while len(records) < maximum:
        params = {"resource_id": spec["resource"], "limit": min(500, maximum-len(records)), "offset": len(records), "fields": spec["fields"]}
        if spec["active"]:
            params["filters"] = json.dumps({"license_state": "Active"})
        page = fetcher.get("https://data.wprdc.org/api/3/action/datastore_search?"+urlencode(params), limit=1_500_000)
        if page["status"] != 200 or page["truncated"]:
            raise ValueError("Public directory response incomplete or unavailable")
        payload = json.loads(page["text"])
        if not payload.get("success"):
            raise ValueError("Public directory query failed")
        rows = payload["result"]["records"]
        total = payload["result"]["total"]
        records.extend(rows)
        if not rows or len(records) >= total:
            break
    observed = stamp()
    source_url = "https://data.wprdc.org/dataset/"+spec["dataset"]+"/resource/"+spec["resource"]
    candidates = []
    for row in records:
        name = str(row.get("business_name") or row.get("firm_name") or "").strip()
        if not name:
            continue
        stable = str(row.get("license_number") or row.get("vendor_id") or normalized_name(name))
        identity = "directory:"+key+":"+hashlib.sha256(stable.encode()).hexdigest()[:20]
        sites = []
        try:
            raw = row.get("website")
            if raw:
                sites = [clean_url(raw if "://" in raw else "https://"+raw)]
        except ValueError:
            pass
        candidate = {"id": identity, "name": name, "category": row.get("license_type_name") or "Public directory business", "websites": sites,
                     "phones": [value] if (value := phone(row.get("primary_phone_number") or row.get("phone_number") or "")) else [],
                     "emails": [value] if (value := email(row.get("email_address") or "")) else [], "social_urls": [],
                     "location_type": "unknown", "service_area": "Pittsburgh license; service area unconfirmed" if spec["active"] else "County directory; service area unconfirmed",
                     "description": str(row.get("work_description") or "")[:700], "source": {"provider": spec["name"], "url": source_url, "collected_at": observed, "license": "CC0-1.0"},
                     "license_evidence": {"number": row.get("license_number"), "state": row.get("license_state"), "expires": row.get("expiration_date"), "issued": row.get("most_recent_issue_date")},
                     "review_status": "new", "business_status": "unknown", "scope_status": "needs_review"}
        candidates.append(candidate)
    return candidates, {"source": key, "observed_at": observed, "returned": len(candidates), "source_total": total, "limited": total > len(records), "url": source_url}


def contact_claims(row, enrichment=None):
    claims = []
    source = row.get("source", {})
    for kind, field in (("website", "websites"), ("phone", "phones"), ("email", "emails"), ("social", "social_urls")):
        for value in row.get(field, []):
            actual_kind = "social" if kind == "website" and social_platform(value) else kind
            claims.append({"kind": actual_kind, "value": value, "source_url": source.get("url"), "observed_at": source.get("collected_at"), "method": source.get("provider", "Listing"), "verification": "listed_not_verified"})
    claims.extend((enrichment or {}).get("contacts", []))
    return list({(c["kind"], c["value"], c.get("source_url")): c for c in claims}.values())


def status_summary(row, workflow, audit=None, enrichment=None):
    claims = contact_claims(row, enrichment)
    kinds = {c["kind"] for c in claims}
    current_url = (audit or {}).get("requested_url") or (enrichment or {}).get("requested_url") or next((u for u in row.get("websites", []) if not social_platform(u)), None)
    independent = bool(current_url and not social_platform(current_url))
    website = "no_independent_url" if not independent else "not_checked"
    checked_at, check_source = None, None
    if audit and independent:
        website = audit.get("reachability", "unknown")
        checked_at, check_source = audit.get("checked_at"), "Technical website audit"
    if enrichment and independent and enrichment.get("requested_url") == current_url and (not checked_at or datetime.fromisoformat(enrichment["checked_at"]) > datetime.fromisoformat(checked_at)):
        first = next(iter(enrichment.get("pages", [])), {})
        website = {"html_observed": "reachable", "partial": "reachable", "http_error": "http_error", "restricted": "restricted", "non_html": "non_html"}.get(first.get("outcome"), "unknown")
        checked_at, check_source = enrichment.get("checked_at"), "Public-page research"
    conflicts = []
    for kind, field in (("phone", "phones"), ("email", "emails")):
        listed = {v.lower() for v in row.get(field, [])}
        observed = {c["value"].lower() for c in (enrichment or {}).get("contacts", []) if c["kind"] == kind}
        if listed and observed and observed-listed:
            conflicts.append(kind)
    operation = workflow.get("business_status", "unknown")
    return {"business": operation, "business_evidence": workflow.get("business_evidence", ""), "business_checked_at": workflow.get("business_checked_at"),
            "identity": "researcher_confirmed" if workflow.get("website_identity") == "confirmed" and current_url and workflow.get("identity_url") == current_url else "unverified",
            "identity_evidence": workflow.get("identity_evidence", ""), "website": website, "website_checked_at": checked_at, "website_check_source": check_source, "contact_disagreements": conflicts,
            "contact": "channels_listed_unverified" if kinds & {"phone", "email", "contact_form", "contact_page"} else "social_only" if "social" in kinds else "no_channels_found",
            "contact_count": len({(c["kind"], c["value"]) for c in claims}), "location_type": row.get("location_type", "mapped_location" if row.get("location") else "unknown"),
            "source": row.get("source", {}).get("provider", "Unknown"), "enrichment_checked_at": (enrichment or {}).get("checked_at")}
