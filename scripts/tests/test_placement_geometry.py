import math
import unittest
from placement_geometry import (usable_spans, check_edge, transform_point,
                                compose, block_transform, segment_polygon_spans, polygons_overlap)


class SupportTests(unittest.TestCase):
    def test_self_intersecting_polygon_with_nonzero_area_is_rejected(self):
        with self.assertRaises(ValueError):
            segment_polygon_spans([0,2],[8,2],[[0,0],[6,4],[0,4],[4,0]],.01)

    def test_concave_collision_shape_is_not_silently_treated_as_convex(self):
        with self.assertRaises(ValueError):
            polygons_overlap([[0,0],[10,0],[10,10],[0,10]],
                [[1,1],[8,1],[8,2],[2,2],[2,8],[1,8]],.01)

    def test_wall_is_split_at_door(self):
        face = {"id": "wall", "a": [0, 120], "b": [4000, 120], "normal": [0, 1]}
        door = {"id": "door", "a": [2560, 0], "b": [3360, 0], "depth": 240}
        self.assertEqual(usable_spans(face, [door], [], .01),
                         [(0, 2560), (3360, 4000)])

    def test_center_outside_door_but_full_edge_overlaps(self):
        f = {"id": "w", "a": [0, 120], "b": [4000, 120], "normal": [0, 1]}
        d = {"id": "d", "a": [2560, 0], "b": [3360, 0], "depth": 240}
        r = check_edge([[2400, 120], [2700, 120]], [0, 1], f, [d], [], .01)
        self.assertEqual(r["status"], "failed")
        self.assertIn("opening_overlap", r["reasons"])

    def test_full_edge_supported_at_door_jamb(self):
        f = {"id": "w", "a": [0, 120], "b": [4000, 120], "normal": [0, 1]}
        d = {"id": "d", "a": [2560, 0], "b": [3360, 0], "depth": 240}
        self.assertEqual(check_edge([[2200, 120], [2500, 120]], [0, 1], f, [d], [], .01)["status"], "passed")

    def test_slanted_face_and_door(self):
        q = math.sqrt(.5)
        f = {"id": "w", "a": [0, 0], "b": [1000*q, 1000*q], "normal": [-q, q]}
        d = {"id": "d", "a": [400*q, 400*q], "b": [600*q, 600*q], "depth": 100}
        spans = usable_spans(f, [d], [], .001)
        self.assertAlmostEqual(spans[0][1], 400)
        self.assertAlmostEqual(spans[1][0], 600)
        self.assertEqual(check_edge([[450*q, 450*q], [550*q, 550*q]], [-q,q], f,[d],[],.001)["status"], "failed")

    def test_column_occludes_existing_wall_face(self):
        f = {"id": "w", "a": [0, 0], "b": [1000, 0], "normal": [0, 1]}
        obstacle = {"id": "column", "polygon": [[400,-100],[600,-100],[600,100],[400,100]]}
        r = check_edge([[450,0],[550,0]], [0,1], f, [], [obstacle], .01)
        self.assertIn("obstacle_overlap", r["reasons"])

    def test_opposite_room_side_is_rejected(self):
        f = {"id":"w","a":[0,0],"b":[1000,0],"normal":[0,1]}
        self.assertIn("wrong_side",check_edge([[10,0],[100,0]],[0,-1],f,[],[],.01)["reasons"])

    def test_short_wall_and_zero_edge_do_not_pass(self):
        f = {"id":"w","a":[0,0],"b":[100,0],"normal":[0,1]}
        self.assertEqual(check_edge([[-1,0],[101,0]],[0,1],f,[],[],.01)["status"],"failed")
        with self.assertRaises(ValueError):
            check_edge([[10,0],[10,0]],[0,1],f,[],[],.01)

    def test_nonfinite_coordinate_is_invalid(self):
        with self.assertRaises(ValueError):
            usable_spans({"a":[0,0],"b":[float("nan"),0]},[],[],.01)

    def test_empty_or_degenerate_obstacle_not_silently_ignored(self):
        with self.assertRaises(ValueError):
            segment_polygon_spans([0,0],[10,0],[[1,1],[2,2]],.01)

    def test_rotated_mirrored_nested_transform(self):
        parent = block_transform({"pos":[10,20],"angle":math.pi/2,"scale":[2,3]})
        child = block_transform({"pos":[1,2],"angle":0,"scale":[-1,1]})
        result = transform_point(compose(parent,child),[4,5])
        self.assertAlmostEqual(result[0],-11)
        self.assertAlmostEqual(result[1],14)


if __name__ == "__main__":
    unittest.main()
