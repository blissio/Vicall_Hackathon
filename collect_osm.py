"""Collect Pittsburgh business candidates from Overpass; Python standard library only."""
import argparse
import csv
import hashlib
import json
import math
import re
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen
from neighborhoods import SOURCE_URL as NEIGHBORHOOD_SOURCE, enrich_neighborhoods

ENDPOINT = "https://overpass-api.de/api/interpreter"
AMENITIES = {"restaurant", "cafe", "fast_food", "bar", "pub", "biergarten",
             "food_court", "ice_cream", "dentist", "doctors", "clinic",
             "veterinary", "pharmacy", "bank", "car_rental", "car_wash"}
TOURISM = {"hotel", "motel", "guest_house", "hostel"}
NONCOMMERCIAL_OFFICES = {"government", "association", "ngo", "political_party",
                         "religion", "diplomatic", "charity"}
INACTIVE = {"no", "vacant", "closed", "disused", "abandoned"}
BOUNDARY_QUERY = '''[out:json][timeout:60];
area["ISO3166-2"="US-PA"]["boundary"="administrative"]->.pa;
rel(area.pa)["boundary"="administrative"]["admin_level"="8"]["name"="Pittsburgh"];
out tags;'''


def now():
    return datetime.now(timezone.utc).isoformat()


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def fetch(query, endpoint, cache_dir, refresh=False):
    """Cache complete responses; reject Overpass runtime errors, including partial data."""
    digest = hashlib.sha256((endpoint + query).encode()).hexdigest()[:20]
    cache = cache_dir / f"{digest}.json"
    if cache.exists() and not refresh:
        return json.loads(cache.read_text(encoding="utf-8"))
    request = Request(endpoint, data=urlencode({"data": query}).encode(),
                      headers={"User-Agent": "VicallHackathonOSMCollector/0.1",
                               "Content-Type": "application/x-www-form-urlencoded"})
    for attempt in range(3):
        try:
            with urlopen(request, timeout=150) as response:
                payload = json.load(response)
            if payload.get("remark"):
                raise ValueError(f"Overpass returned incomplete data: {payload['remark']}")
            if not isinstance(payload.get("elements"), list):
                raise ValueError("Overpass response is missing elements")
            envelope = {"collected_at": now(), "endpoint": endpoint, "query": query,
                        "payload": payload}
            write_json(cache, envelope)
            return envelope
        except HTTPError as exc:
            if exc.code not in {429, 502, 503, 504} or attempt == 2:
                raise
            retry = exc.headers.get("Retry-After", "")
            delay = max(20 * (attempt + 1), int(retry) if retry.isdigit() else 0)
        except (URLError, TimeoutError):
            if attempt == 2:
                raise
            delay = 20 * (attempt + 1)
        print(f"Overpass temporarily unavailable; retrying in {delay}s", file=sys.stderr)
        time.sleep(delay)


def business_query(relation_id):
    amenity = "|".join(sorted(AMENITIES))
    tourism = "|".join(sorted(TOURISM))
    return f'''[out:json][timeout:120];
rel({int(relation_id)}); map_to_area->.city;
(
  nwr(area.city)["shop"];
  nwr(area.city)["office"];
  nwr(area.city)["craft"];
  nwr(area.city)["amenity"~"^({amenity})$"];
  nwr(area.city)["tourism"~"^({tourism})$"];
);
out meta center;'''


def tidy(value):
    return " ".join(str(value).split()) if value is not None else ""


def category(tags):
    if any(tags.get(k) == "yes" for k in ("disused", "abandoned", "demolished", "closed")):
        return None
    for key in ("shop", "craft", "office", "amenity", "tourism"):
        value = tags.get(key)
        if not value or value in INACTIVE:
            continue
        if key == "office" and value in NONCOMMERCIAL_OFFICES:
            continue
        if key == "amenity" and value not in AMENITIES:
            continue
        if key == "tourism" and value not in TOURISM:
            continue
        return f"{key}:{value}"
    return None


def website(value):
    if not value:
        return None
    value = tidy(value)
    if any(char.isspace() for char in value):
        return None
    if "://" not in value:
        value = "https://" + value
    try:
        parts = urlsplit(value)
        if parts.scheme not in {"http", "https"} or not parts.hostname or "." not in parts.hostname:
            return None
        if parts.username or parts.password:
            return None
        port = parts.port
        host = parts.hostname.lower()
        authority = host + (f":{port}" if port else "")
        return urlunsplit((parts.scheme.lower(), authority, parts.path or "/", parts.query, ""))
    except ValueError:
        return None


def contacts(tags, key):
    values = []
    for tag in (key, f"contact:{key}"):
        for value in tags.get(tag, "").split(";"):
            value = tidy(value)
            if value and value not in values:
                values.append(value)
    return values


def normalize(element, collected_at):
    tags = element.get("tags", {})
    kind = category(tags)
    name = tidy(tags.get("name"))
    if not kind:
        return None, "not_active_business_candidate"
    if not name:
        return None, "unnamed"
    flags = []
    sites_raw = contacts(tags, "website")
    sites = list(dict.fromkeys(url for value in sites_raw if (url := website(value))))
    if len(sites) != len(sites_raw):
        flags.append("website_values_need_review")
    emails_raw = contacts(tags, "email")
    emails = [v for v in emails_raw if re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", v)]
    if len(emails) != len(emails_raw):
        flags.append("email_values_need_review")
    phones_raw = contacts(tags, "phone")
    phones = []
    for raw in phones_raw:
        digits = re.sub(r"\D", "", raw)
        # US-only normalization; retain extensions and unusual formats as raw data.
        if re.fullmatch(r"[+\d() .-]+", raw) and (len(digits) == 10 or (len(digits) == 11 and digits.startswith("1"))):
            phones.append("+1" + digits[-10:])
        else:
            flags.append("phone_values_need_review")
    point = element if "lat" in element else element.get("center", {})
    lat, lon = point.get("lat"), point.get("lon")
    location = {"type": "Point", "coordinates": [lon, lat]} if lat is not None and lon is not None else None
    if not location:
        flags.append("missing_coordinates")
    address = {key: tidy(tags.get(f"addr:{tag}")) or None for key, tag in
               (("house_number", "housenumber"), ("street", "street"), ("unit", "unit"),
                ("city", "city"), ("state", "state"), ("postcode", "postcode"))}
    if not address["house_number"] or not address["street"]:
        flags.append("incomplete_street_address")
    identity = f"osm:{element['type']}:{element['id']}"
    record = {"_id": identity, "name": name, "category": kind, "address": address,
              "location": location, "coordinate_method": "node" if "lat" in element else "bounding_box_center",
              "websites": sites, "website_status": "listed_in_osm_unverified" if sites else
              ("invalid_osm_value" if sites_raw else "not_listed_in_osm"),
              "phones": list(dict.fromkeys(phones)), "emails": emails,
              "contact_values_raw": {"website": sites_raw, "phone": phones_raw, "email": emails_raw},
              "brand": tags.get("brand"), "operator": tags.get("operator"),
              "ownership_status": "unknown", "business_size_status": "unknown",
              "opening_hours": tags.get("opening_hours"), "quality_flags": sorted(set(flags)),
              "duplicate_candidates": [], "raw_tags": tags,
              "source": {"provider": "OpenStreetMap", "osm_type": element["type"],
                         "osm_id": element["id"], "osm_version": element.get("version"),
                         "osm_last_modified": element.get("timestamp"), "collected_at": collected_at,
                         "url": f"https://www.openstreetmap.org/{element['type']}/{element['id']}",
                         "license": "ODbL-1.0", "attribution": "© OpenStreetMap contributors"}}
    return record, None


def distance(a, b):
    lon1, lat1 = map(math.radians, a["coordinates"])
    lon2, lat2 = map(math.radians, b["coordinates"])
    h = math.sin((lat2-lat1)/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin((lon2-lon1)/2)**2
    return 6371000 * 2 * math.asin(min(1, math.sqrt(h)))


def clean(envelope):
    records = {}
    skipped = Counter()
    for element in envelope["payload"]["elements"]:
        record, reason = normalize(element, envelope["collected_at"])
        if reason:
            skipped[reason] += 1
        elif record["_id"] in records:
            skipped["repeated_osm_id"] += 1
        else:
            records[record["_id"]] = record
    groups = defaultdict(list)
    for record in records.values():
        groups[record["name"].casefold()].append(record)
    # Flag possible node/building duplicates. Do not merge branches or erase provenance.
    for group in groups.values():
        for index, a in enumerate(group):
            for b in group[index+1:]:
                if a["location"] and b["location"] and distance(a["location"], b["location"]) <= 40:
                    a["duplicate_candidates"].append(b["_id"])
                    b["duplicate_candidates"].append(a["_id"])
    rows = sorted(records.values(), key=lambda row: row["_id"])
    report = {"raw_elements": len(envelope["payload"]["elements"]), "cleaned_candidates": len(rows),
              "skipped": dict(skipped), "with_listed_website": sum(bool(r["websites"]) for r in rows),
              "with_phone": sum(bool(r["phones"]) for r in rows),
              "with_email": sum(bool(r["emails"]) for r in rows),
              "with_complete_street_address": sum(bool(r["address"]["house_number"] and r["address"]["street"]) for r in rows),
              "records_with_duplicate_candidates": sum(bool(r["duplicate_candidates"]) for r in rows),
              "categories": dict(Counter(r["category"] for r in rows)),
              "collected_at": envelope["collected_at"], "osm_data_timestamp": envelope["payload"].get("osm3s", {}).get("timestamp_osm_base"),
              "scope": "Pittsburgh city administrative boundary; selected business tags",
              "limitations": ["Not a complete business census", "Business size and independence are unknown",
                              "Missing OSM website/contact fields mean unknown", "Duplicate candidates require review"],
              "attribution": "© OpenStreetMap contributors", "license_url": "https://www.openstreetmap.org/copyright"}
    return rows, report


def export(envelope, output):
    rows, report = clean(envelope)
    enrich_neighborhoods(rows)
    report["neighborhoods"] = dict(Counter(r["neighborhood"] or "Unknown" for r in rows))
    report["neighborhood_source"] = NEIGHBORHOOD_SOURCE
    write_json(output / "raw" / "businesses.json", envelope)
    target = output / "processed"
    target.mkdir(parents=True, exist_ok=True)
    (target / "businesses.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    fields = ["id", "name", "category", "neighborhood", "neighborhood_method", "neighborhood_source", "street_address", "city", "postcode", "website", "website_status", "phone", "email", "source_url"]
    with (target / "businesses.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for r in rows:
            a = r["address"]
            values = {"id": r["_id"], "name": r["name"], "category": r["category"],
                      "neighborhood": r.get("neighborhood"), "neighborhood_method": r.get("neighborhood_method"), "neighborhood_source": NEIGHBORHOOD_SOURCE,
                      "street_address": " ".join(v for v in (a["house_number"], a["street"], a["unit"]) if v),
                      "city": a["city"], "postcode": a["postcode"], "website": "; ".join(r["websites"]),
                      "website_status": r["website_status"], "phone": "; ".join(r["phones"]),
                      "email": "; ".join(r["emails"]), "source_url": r["source"]["url"]}
            # Protect spreadsheet viewers from formulas originating in OSM free-text tags.
            writer.writerow({k: "'" + v if isinstance(v, str) and v.startswith(("=", "+", "-", "@")) else v for k, v in values.items()})
    write_json(target / "quality_report.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("data"))
    parser.add_argument("--endpoint", default=ENDPOINT)
    parser.add_argument("--refresh", action="store_true", help="Fetch fresh data instead of reusing the cache")
    parser.add_argument("--input", type=Path, help="Re-clean an existing raw envelope, without network requests")
    args = parser.parse_args()
    if args.input:
        envelope = json.loads(args.input.read_text(encoding="utf-8"))
    else:
        boundary = fetch(BOUNDARY_QUERY, args.endpoint, args.output / "cache", args.refresh)
        relations = boundary["payload"]["elements"]
        if len(relations) != 1 or relations[0]["type"] != "relation":
            raise ValueError(f"Expected one Pittsburgh boundary, found {len(relations)}; inspect boundary query")
        write_json(args.output / "raw" / "boundary.json", boundary)
        query = business_query(relations[0]["id"])
        args.output.mkdir(parents=True, exist_ok=True)
        (args.output / "collection_query.overpassql").write_text(query + "\n", encoding="utf-8")
        print(f"Collecting businesses within Pittsburgh relation {relations[0]['id']}...", flush=True)
        envelope = fetch(query, args.endpoint, args.output / "cache", args.refresh)
    report = export(envelope, args.output)
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, TimeoutError) as exc:
        print(f"Collection failed: {exc}", file=sys.stderr)
        sys.exit(1)
