import unittest

from neighborhoods import NeighborhoodIndex, city_index, enrich_neighborhoods


def feature(name, rings, kind="Polygon"):
    return {"properties": {"hood": name}, "geometry": {"type": kind, "coordinates": rings}}


class NeighborhoodTests(unittest.TestCase):
    def test_polygon_holes_multipart_and_shared_boundary(self):
        left = [[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]
        hole = [[.5, .5], [.5, 1.5], [1.5, 1.5], [1.5, .5], [.5, .5]]
        right = [[2, 0], [4, 0], [4, 2], [2, 2], [2, 0]]
        island = [[5, 0], [6, 0], [6, 1], [5, 1], [5, 0]]
        index = NeighborhoodIndex({"features": [feature("Left", [left, hole]), feature("Right", [[right], [island]], "MultiPolygon")]})
        self.assertEqual(index.locate([.2, .2]), ["Left"])
        self.assertEqual(index.locate([1, 1]), [])
        self.assertEqual(index.locate([5.5, .5]), ["Right"])
        self.assertEqual(index.locate([2, 1]), ["Left", "Right"])
        rows = [{"location": {"coordinates": [2, 1]}, "coordinate_method": "node"}]
        enrich_neighborhoods(rows, index)
        self.assertIsNone(rows[0]["neighborhood"])
        self.assertEqual(rows[0]["neighborhood_method"], "boundary_ambiguous")

    def test_invalid_missing_and_outside_coordinates_remain_unknown(self):
        index = city_index()
        for value in (None, [], [True, 40], [float("nan"), 40], ["-80", 40], [-70, 30]):
            self.assertEqual(index.locate(value), [])
        row = {"location": None}
        enrich_neighborhoods([row])
        self.assertIsNone(row["neighborhood"])

    def test_bundled_city_boundaries_and_real_business_locations(self):
        index = city_index()
        self.assertEqual(len({name for name, _, _ in index.polygons}), 90)
        self.assertEqual(index.locate([-79.9510172, 40.4828447]), ["Upper Lawrenceville"])
        self.assertEqual(index.locate([-79.9848271, 40.4289672]), ["South Side Flats"])
        self.assertEqual(index.locate([-80.0159649, 40.4519059]), ["Allegheny West"])
        row = {"location": {"coordinates": [-79.9848271, 40.4289672]}, "coordinate_method": "bounding_box_center"}
        enrich_neighborhoods([row])
        self.assertEqual(row["neighborhood_method"], "approximate_area_center")


if __name__ == "__main__":
    unittest.main()
