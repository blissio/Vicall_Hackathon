"""Build an isolated fictional offline demo; never mixes with live research."""
import argparse
import json
from pathlib import Path

from storage import save_document, stamp


def build_demo(directory):
    directory = Path(directory)
    if directory.exists() and any(directory.iterdir()):
        raise ValueError("Choose an empty directory for the fictional demo")
    (directory / "processed").mkdir(parents=True, exist_ok=True)
    observed = stamp()
    definitions = [
        ("accounting-issues", "Demo River Accounting", "office:accountant", "business", "Accounting, tax preparation, bookkeeping", 45),
        ("accounting-strong", "Demo Oak Accounting", "office:accountant", "business", "Accounting and audit services", 95),
        ("accounting-blocked", "Demo Hill Accounting", "office:accountant", "business", "Accounting services", None),
        ("legal", "Demo Bridge Legal", "office:lawyer", "business", "Legal advice and business contracts", 90),
        ("technology", "Demo Steel Technology", "office:it", "business", "Software and managed technology services", 85),
        ("district", "Demo Pittsburgh School District", "education:school_district", "school_district", "Public education", 65),
        ("school", "Demo Neighborhood School", "amenity:school", "school", "Elementary education", 90),
        ("cafe", "Demo Neighborhood Cafe", "amenity:cafe", "business", "Coffee and catering", 75),
    ]
    rows, audits = [], {}
    for key, name, category, kind, services, score in definitions:
        identity, url = "demo:"+key, "https://"+key+".example.test/"
        row = {"_id": identity, "name": name, "category": category, "address": {}, "location": None,
               "websites": [url], "emails": ["office@"+key+".example.test"], "phones": [], "social_urls": [],
               "website_status": "listed_external_unverified", "quality_flags": ["fictional_demo"], "duplicate_candidates": [],
               "location_type": "service_area", "service_area": "Pittsburgh (fictional demonstration)",
               "source": {"url": url, "provider": "Fictional demonstration fixture", "collected_at": observed}}
        rows.append(row)
        audit = {"requested_url": url, "final_url": url, "checked_at": observed, "reachability": "reachable" if score is not None else "inconclusive",
                 "score": score, "grade": "strong" if score is not None and score >= 80 else "review" if score is not None and score >= 50 else "needs_work" if score is not None else "unknown", "checks": [], "audit_version": "demo", "message": "Fictional audit fixture, not a real website check",
                 "target_source": "fictional_demo", "recommendations": [{"label": "Demo metadata issue", "recommendation": "Review title and description", "evidence": "Fictional missing metadata"}] if score is not None and score < 80 else []}
        audits[identity] = {"latest": audit, "history": []}
    (directory / "processed" / "businesses.jsonl").write_text("".join(json.dumps(r)+"\n" for r in rows), encoding="utf-8")
    (directory / "processed" / "quality_report.json").write_text(json.dumps({"collected_at": observed, "cleaned_records": len(rows), "demo": True}), encoding="utf-8")
    (directory / "DEMO.json").write_text(json.dumps({"fictional": True, "created_at": observed}), encoding="utf-8")
    save_document(directory / "website_audits.json", audits)
    from app import Workspace
    workspace = Workspace(directory)
    for key, name, category, kind, services, score in definitions:
        url = "https://"+key+".example.test/"
        workspace.save_organization({"id": "demo:"+key, "organization_type": kind, "services": services,
            "parent_id": "demo:district" if key == "school" else "", "source_url": url, "observed_at": observed,
            "excerpt": "Fictional demo organization provides: "+services})
    for key, role in (("accounting-issues", "Managing partner"), ("district", "Communications director")):
        workspace.save_person({"business_id": "demo:"+key, "name": "Demo Contact "+key, "role": role,
            "source_url": "https://"+key+".example.test/team", "observed_at": observed,
            "excerpt": "Fictional demonstration person with the stated public role; no real person or authority implied"})
    return workspace


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(__file__).parent / "demo_data")
    args = parser.parse_args()
    build_demo(args.output)
    print(f"Created fictional offline demo in {args.output.resolve()}\nRun python app.py --data-dir \"{args.output.resolve()}\"")
