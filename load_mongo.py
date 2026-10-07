"""Optional MongoDB loader. Install pymongo and set MONGODB_URI first."""
import argparse
import json
import os
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("data/processed/businesses.jsonl"))
    parser.add_argument("--database", default="vicall")
    args = parser.parse_args()
    uri = os.environ.get("MONGODB_URI")
    if not uri:
        parser.error("Set MONGODB_URI in your environment; do not put credentials in source files")
    try:
        from pymongo import MongoClient
    except ImportError:
        parser.error("Install the optional dependency with: python -m pip install pymongo")
    # Keep OSM and later website/AI research in separate collections.
    # Repeated runs update the same OSM IDs instead of inserting duplicates.
    count = 0
    with MongoClient(uri, serverSelectionTimeoutMS=10000) as client:
        client.admin.command("ping")
        collection = client[args.database]["osm_businesses"]
        collection.create_index("category")
        collection.create_index("website_status")
        collection.create_index([("location", "2dsphere")])
        with args.input.open(encoding="utf-8") as handle:
            for line in handle:
                record = json.loads(line)
                identity = record.pop("_id")
                # OSM keys are arbitrary strings; store as pairs to avoid Mongo field-name issues.
                record["raw_tags"] = [{"key": k, "value": v} for k, v in record["raw_tags"].items()]
                collection.update_one({"_id": identity}, {"$set": record}, upsert=True)
                count += 1
    print(f"Upserted {count} records into {args.database}.osm_businesses")


if __name__ == "__main__":
    main()
