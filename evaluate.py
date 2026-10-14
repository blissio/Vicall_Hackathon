"""Repeatable fixture retrieval evaluation; never claims real lead conversion."""
import argparse
import json
import tempfile
from pathlib import Path
from time import perf_counter
from demo import build_demo
from intelligence import segment

CASES = [
    {"name": "Office prospects with observed issues", "query": {"question": "Find accounting firms", "require_website_issue": True, "require_contact": True}, "relevant": ["demo:accounting-issues"]},
    {"name": "District public role", "query": {"question": "school districts", "organization_type": "school_district", "require_decision_maker": True}, "relevant": ["demo:district"]},
    {"name": "Legal provider", "query": {"question": "legal advice", "intent": "providers"}, "relevant": ["demo:legal"]},
    {"name": "Unrepresented category", "query": {"question": "veterinary"}, "relevant": []},
]


def evaluate(workspace, cases):
    report = {"dataset": "fictional fixtures", "cases": [], "limitations": ["Synthetic relevance labels; not client-reviewed lead quality", "No live model calls or external website fetching", "Context sizes are characters, not measured model tokens", "Latency describes local retrieval only"]}
    all_evidence = [workspace.intelligence_detail(row["_id"])["evidence"] for row in workspace.rows]
    full_context = len(json.dumps(all_evidence, ensure_ascii=False))
    for case in cases:
        before = perf_counter()
        answer = workspace.search_businesses(case["query"])
        elapsed = (perf_counter()-before)*1000
        actual = [r["id"] for r in answer["results"]]
        expected = set(case["relevant"])
        matches = len(set(actual) & expected)
        # Category/sector-only baseline removes the evidence requirements.
        baseline_query = {k: v for k,v in case["query"].items() if not k.startswith("require_") and k != "organization_type"}
        baseline = workspace.search_businesses(baseline_query)
        baseline_ids = [r["id"] for r in baseline["results"]]
        context = len(json.dumps([r["evidence"] for r in answer["results"]], ensure_ascii=False))
        report["cases"].append({"name": case["name"], "expected_ids": sorted(expected), "actual_ids": actual,
            "precision": matches/len(actual) if actual else None, "recall": matches/len(expected) if expected else None,
            "exact_set_match": set(actual) == expected,
            "baseline_precision": len(set(baseline_ids)&expected)/len(baseline_ids) if baseline_ids else None,
            "retrieval_ms": round(elapsed, 2), "retrieved_context_characters": context, "full_context_characters": full_context,
            "external_page_requests": answer["metrics"]["external_page_requests"]})
    report["exact_set_matches"] = sum(c["exact_set_match"] for c in report["cases"])
    report["case_count"] = len(cases)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("docs/evaluation.json"))
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
        report = evaluate(build_demo(directory), CASES)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"exact_set_matches": report["exact_set_matches"], "case_count": report["case_count"], "output": str(args.output)}))
