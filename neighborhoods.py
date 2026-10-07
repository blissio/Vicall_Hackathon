"""Offline point-in-polygon matching against Pittsburgh's city neighborhood layer."""
import json
import math
from functools import lru_cache
from pathlib import Path

SOURCE_URL = "https://pghbridgis.pittsburghpa.gov/federated/rest/services/Neighborhoods/FeatureServer/0"
BOUNDARIES = Path(__file__).resolve().parent / "assets" / "pittsburgh-neighborhoods.geojson"


def ring_contains(x, y, ring):
    """Return inside/boundary/outside; handle either ring orientation."""
    inside = False
    for a, b in zip(ring, ring[1:] + ring[:1]):
        ax, ay = a[:2]
        bx, by = b[:2]
        cross = (x - ax) * (by - ay) - (y - ay) * (bx - ax)
        if abs(cross) <= 1e-12 and min(ax, bx)-1e-10 <= x <= max(ax, bx)+1e-10 and min(ay, by)-1e-10 <= y <= max(ay, by)+1e-10:
            return "boundary"
        if (ay > y) != (by > y) and x < ax + (y-ay)*(bx-ax)/(by-ay):
            inside = not inside
    return "inside" if inside else "outside"


def polygon_contains(x, y, rings):
    outer = ring_contains(x, y, rings[0])
    if outer == "outside":
        return False
    for hole in rings[1:]:
        if ring_contains(x, y, hole) == "inside":
            return False
    return True


class NeighborhoodIndex:
    def __init__(self, collection):
        self.polygons = []
        for feature in collection["features"]:
            name = feature["properties"]["hood"]
            geometry = feature["geometry"]
            if geometry["type"] not in {"Polygon", "MultiPolygon"}:
                raise ValueError("Neighborhood boundaries must be polygons")
            polygons = [geometry["coordinates"]] if geometry["type"] == "Polygon" else geometry["coordinates"]
            for rings in polygons:
                xs, ys = zip(*(point[:2] for point in rings[0]))
                self.polygons.append((name, (min(xs), min(ys), max(xs), max(ys)), rings))

    def locate(self, coordinates):
        if not isinstance(coordinates, (list, tuple)) or len(coordinates) != 2:
            return []
        x, y = coordinates
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in (x, y)):
            return []
        matches = set()
        for name, (left, bottom, right, top), rings in self.polygons:
            if left-1e-10 <= x <= right+1e-10 and bottom-1e-10 <= y <= top+1e-10 and polygon_contains(x, y, rings):
                matches.add(name)
        return sorted(matches)


@lru_cache(maxsize=1)
def city_index():
    return NeighborhoodIndex(json.loads(BOUNDARIES.read_text(encoding="utf-8")))


def enrich_neighborhoods(rows, index=None):
    index = index or city_index()
    for row in rows:
        matches = index.locate((row.get("location") or {}).get("coordinates"))
        row["neighborhood"] = matches[0] if len(matches) == 1 else None
        row["neighborhood_method"] = ("mapped_point" if row.get("coordinate_method") == "node" else "approximate_area_center") if len(matches) == 1 else "boundary_ambiguous" if matches else "unmatched"
        row["neighborhood_candidates"] = matches if len(matches) > 1 else []
    return rows
