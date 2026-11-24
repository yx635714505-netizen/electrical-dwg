import copy
import math
import unittest
from verify_placement import validate_geometry, socket_mount, socket_mount_from_chord, flatten


def source():
    return {"faces":[{"id":"W","floor":"F","a":[0,0],"b":[1000,0],"normal":[0,1]}],
            "openings":[{"id":"D","floor":"F","a":[400,0],"b":[600,0],"depth":100}],
            "obstacles":[], "pending":[]}


def instance(edge=None, ident="P"):
    edge=edge or [[100,0],[200,0]]
    return {"id":ident,"floor":"F","sheet":"S","kind":"socket","handles":[ident],
            "mountingEdge":edge,"normal":[0,1],"physical_id":ident,
            "footprint":[edge[0],edge[1],[edge[1][0],edge[1][1]+30],[edge[0][0],edge[0][1]+30]]}


class VerifyTests(unittest.TestCase):
    def test_missing_body_footprint_blocks_full_geometry_acceptance(self):
        v=instance();del v["footprint"]
        self.assertEqual(validate_geometry(source(),[v],.01)["status"],"pending")

    def test_support_only_report_cannot_be_full_geometry_acceptance(self):
        r=validate_geometry(source(),[instance()],.01,support_only=True)
        self.assertFalse(r["acceptanceEligible"])

    def test_reviewed_semicircle_profile_uses_actual_chord_line(self):
        d={"blocks":{"x":[{"h":"A","type":"ARC","bbox":[[-5,-5],[5,0]]},
            {"h":"L","type":"LINE","vertices":[[-5,0],[5,0]]}]}}
        mount=socket_mount_from_chord(d,{"h":"R","type":"INSERT","block":"x"},.01)
        self.assertEqual(mount["status"],"passed")
        self.assertEqual(mount["normal"],(0.,-1.))
        self.assertEqual(mount["chord"],"L")

    def test_reviewed_profile_does_not_guess_when_chord_missing(self):
        d={"blocks":{"x":[{"h":"A","type":"ARC","bbox":[[-5,-5],[5,0]]}]}}
        self.assertEqual(socket_mount_from_chord(d,{"h":"R","type":"INSERT","block":"x"},.01)["status"],"pending")

    def test_column_face_itself_is_an_installable_visible_surface(self):
        s={"faces":[{"id":"C:top","source_handle":"C","floor":"F","a":[0,0],"b":[1000,0],"normal":[0,1]}],
           "openings":[],"obstacles":[{"id":"C","floor":"F","polygon":[[0,-100],[1000,-100],[1000,0],[0,0]]}],"pending":[]}
        self.assertEqual(validate_geometry(s,[instance()],.01)["status"],"passed")

    def test_native_mount_edge_from_actual_rotated_arc_chord(self):
        detail={"blocks":{"*Model_Space":[],
                "outer":[{"h":"B","type":"INSERT","block":"inner","pos":[10,20],"scale":[-2,3],"angle":math.pi/2}],
                "inner":[{"h":"A","type":"ARC","center":[0,0],"start":[-5,0],"end":[5,0],"mid":[0,5],"sweep":math.pi}]}}
        root={"h":"ROOT","type":"INSERT","block":"outer","pos":[0,0],"scale":[1,1],"angle":0}
        mount=socket_mount(detail,root)
        self.assertEqual(mount["status"],"passed")
        self.assertAlmostEqual(mount["edge"][0][0],10)
        self.assertAlmostEqual(mount["edge"][0][1],30)
        self.assertEqual([round(n) for n in mount["normal"]],[-1,0])

    def test_arc_without_native_endpoints_is_pending_not_guessed(self):
        detail={"blocks":{"x":[{"h":"A","type":"ARC","bbox":[[0,0],[10,5]]}]}}
        root={"h":"R","type":"INSERT","block":"x"}
        self.assertEqual(socket_mount(detail,root)["status"],"pending")

    def test_ambiguous_two_socket_bodies_is_pending(self):
        arc={"h":"A","type":"ARC","center":[0,0],"start":[-5,0],"end":[5,0],"mid":[0,5],"sweep":math.pi}
        arc2=dict(arc,h="B")
        d={"blocks":{"x":[arc,arc2]}}
        self.assertEqual(socket_mount(d,{"h":"R","type":"INSERT","block":"x"})["status"],"pending")

    def test_uses_actual_edge_and_opening_not_expected_coordinate(self):
        v=instance([[450,0],[550,0]])
        v["expectedPosition"]=[100,0]
        r=validate_geometry(source(),[v],.01)
        self.assertEqual(r["status"],"failed")
        self.assertIn("opening_overlap",r["points"][0]["reasons"])

    def test_missing_install_edge_is_pending(self):
        v=instance();del v["mountingEdge"]
        self.assertEqual(validate_geometry(source(),[v],.01)["status"],"pending")

    def test_missing_floor_geometry_is_pending(self):
        v=instance();v["floor"]="other"
        self.assertEqual(validate_geometry(source(),[v],.01)["status"],"pending")

    def test_colocated_different_physical_panels_fail(self):
        a=instance();b=instance(ident="Q")
        r=validate_geometry(source(),[a,b],.01)
        self.assertEqual(r["status"],"failed")
        self.assertTrue(r["collisions"])

    def test_same_physical_panel_on_other_sheet_is_not_a_duplicate(self):
        a=instance();b=instance(ident="Q");b["physical_id"]="P";b["sheet"]="S2"
        self.assertEqual(validate_geometry(source(),[a,b],.01)["status"],"passed")

    def test_same_physical_id_cannot_hide_cross_sheet_position_difference(self):
        a=instance();b=instance([[250,0],[350,0]],ident="Q")
        b["physical_id"]="P";b["sheet"]="S2"
        self.assertEqual(validate_geometry(source(),[a,b],.01)["status"],"failed")

    def test_zero_based_floor_identifier_is_valid(self):
        s=source()
        for item in s["faces"]+s["openings"]:item["floor"]=0
        v=instance();v["floor"]=0
        self.assertEqual(validate_geometry(s,[v],.01)["status"],"passed")

    def test_duplicate_actual_id_fails(self):
        self.assertEqual(validate_geometry(source(),[instance(),instance()],.01)["status"],"failed")

    def test_invalid_source_geometry_remains_pending(self):
        s=source();s["openings"][0]["depth"]=0
        self.assertEqual(validate_geometry(s,[instance()],.01)["status"],"pending")

    def test_partial_source_extraction_cannot_pass(self):
        s=source();s["pending"]=[{"floor":"F","handle":"curved-wall","reason":"unsupported"}]
        self.assertEqual(validate_geometry(s,[instance()],.01)["status"],"pending")

    def test_cyclic_block_does_not_disappear_silently(self):
        d={"blocks":{"x":[{"h":"B","type":"INSERT","block":"x"}]}}
        with self.assertRaises(ValueError):
            list(flatten(d,{"h":"A","type":"INSERT","block":"x"}))


if __name__=="__main__":unittest.main()
