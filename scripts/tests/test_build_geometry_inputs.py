import unittest
from build_geometry_inputs import adapt_source, extract_instances


class AdapterTests(unittest.TestCase):
    def test_declared_native_edge_can_use_an_actual_closed_body_outline(self):
        native={"blocks":{"*Model_Space":[{"h":"R","type":"INSERT","layer":"EQUIP-箱体","block":"panel","bbox":[[0,0],[100,40]]}],
            "panel":[{"h":"edge","type":"LINE","vertices":[[0,0],[100,0]]},
                     {"h":"body","type":"LWPOLYLINE","closed":True,"vertices":[[0,0],[100,0],[100,40],[0,40]],"bulges":[0,0,0,0]}]}}
        profile={"layer":"EQUIP-箱体","kind":"panel","extractor":"declared-native-edge","primitive":"edge","bodyPrimitive":"body","normal":[0,1]}
        r=extract_instances(native,[{"id":"S","floor":"F","region":[[-1,-1],[200,200]]}],[profile])[0]
        self.assertEqual(r["footprint"],[(0.,0.),(100.,0.),(100.,40.),(0.,40.)])

    def test_declared_edge_is_pending_if_repeated_nested_handle_is_ambiguous(self):
        native={"blocks":{"*Model_Space":[{"h":"R","type":"INSERT","layer":"EQUIP-箱体","block":"panel","bbox":[[0,0],[100,40]]}],
            "panel":[{"h":"c1","type":"INSERT","block":"child"},{"h":"c2","type":"INSERT","block":"child"}],
            "child":[{"h":"edge","type":"LINE","vertices":[[0,0],[100,0]]}]}}
        profile={"layer":"EQUIP-箱体","kind":"panel","extractor":"declared-native-edge","primitive":"edge","normal":[0,1]}
        r=extract_instances(native,[{"id":"S","floor":"F","region":[[-1,-1],[200,200]]}],[profile])[0]
        self.assertEqual(r["geometry_status"],"pending")

    def test_perpendicular_wall_body_blocks_a_hidden_face(self):
        from verify_placement import validate_geometry
        entities=[{"handle":"W","type":"TCH_WALL","grips":[[0,0],[1000,0],[500,0]],"bbox":[[0,-50],[1000,50]]},
            {"handle":"V","type":"TCH_WALL","grips":[[200,0],[200,1000],[200,500]],"bbox":[[150,0],[250,1000]]}]
        s=adapt_source(entities,[{"id":"F","region":[[-100,-100],[1200,1200]],"transform":[1,0,0,1,0,0]}],.01)
        r=validate_geometry(s,[{"id":"P","sheet":"S","floor":"F","handles":["P"],"mountingEdge":[[160,50],[240,50]],"normal":[0,1],"footprint":[[160,50],[240,50],[240,80],[160,80]]}],.01)
        self.assertEqual(r["status"],"failed")

    def test_unclassified_nested_furniture_is_pending(self):
        s=adapt_source([{"handle":"B","type":"INSERT","layer":"家具","bbox":[[0,0],[100,100]]}],
             [{"id":"F","region":[[-10,-10],[200,200]],"transform":[1,0,0,1,0,0]}],.01)
        self.assertTrue(s["pending"])

    def test_offset_wall_axis_is_not_assumed_to_be_thickness_center(self):
        entities=[{"handle":"W","type":"TCH_WALL","grips":[[0,120],[1000,120],[500,120]],"bbox":[[0,0],[1000,120]]}]
        s=adapt_source(entities,[{"id":"F","region":[[-10,-200],[1100,200]],"transform":[1,0,0,1,0,0]}],.01)
        self.assertEqual(sorted(f["a"][1] for f in s["faces"]),[0,120])

    def test_door_swing_extents_do_not_inflate_aperture_wall_thickness(self):
        entities=[{"handle":"W","type":"TCH_WALL","grips":[[0,120],[1000,120],[500,120]],"bbox":[[0,0],[1000,120]]},
            {"handle":"D","type":"TCH_OPENING","grips":[[500,60],[400,60],[600,60]],"bbox":[[400,0],[600,800]]}]
        s=adapt_source(entities,[{"id":"F","region":[[-10,-200],[1100,900]],"transform":[1,0,0,1,0,0]}],.01)
        self.assertEqual(s["openings"][0]["depth"],120)

    def test_native_wall_face_minus_aperture_not_bbox_only(self):
        entities=[
            {"handle":"W","type":"TCH_WALL","grips":[[0,0],[1000,0],[500,0]],"bbox":[[0,-120],[1000,120]]},
            {"handle":"D","type":"TCH_OPENING","grips":[[500,0],[400,0],[600,0]],"bbox":[[400,-120],[600,120]]}]
        source=adapt_source(entities,[{"id":"F","region":[[-10,-200],[1100,200]],"transform":[1,0,0,1,0,0]}],.01)
        self.assertEqual(len(source["faces"]),2)
        self.assertEqual(source["openings"][0]["depth"],240)
        self.assertFalse(source["pending"])

    def test_curved_wall_or_missing_source_geometry_remains_pending(self):
        source=adapt_source([{"handle":"W","type":"TCH_WALL","grips":[[0,0],[1000,0],[500,50]],"bbox":[[0,-100],[1000,100]]}],
             [{"id":"F","region":[[-10,-200],[1100,200]],"transform":[1,0,0,1,0,0]}],.01)
        self.assertTrue(source["pending"])
        self.assertFalse(source["faces"])

    def test_no_profile_does_not_drop_actual_equipment(self):
        detail={"blocks":{"*Model_Space":[{"h":"R","type":"INSERT","layer":"EQUIP-插座","block":"x","bbox":[[1,1],[3,3]]}],"x":[]}}
        result=extract_instances(detail,[{"id":"S","floor":"F","region":[[0,0],[100,100]],"transform":[1,0,0,1,0,0]}],[])
        self.assertEqual(len(result),1)
        self.assertEqual(result[0]["geometry_status"],"pending")

    def test_square_column_actual_closed_vertices_are_used(self):
        source=adapt_source([{"handle":"C","type":"TCH_COLUMN","bbox":[[0,0],[100,100]],"visibleParts":[{"type":"LWPOLYLINE","closed":True,"bulges":[0,0,0,0],"vertices":[[0,0],[100,0],[100,100],[0,100]]}]}],
             [{"id":"F","region":[[-10,-10],[200,200]],"transform":[1,0,0,1,0,0]}],.01)
        self.assertEqual(len(source["obstacles"]),1)
        self.assertFalse(source["pending"])

    def test_wall_bbox_without_native_centerline_is_not_support_proof(self):
        source=adapt_source([{"handle":"W","type":"TCH_WALL","bbox":[[0,-100],[1000,100]]}],
             [{"id":"F","region":[[-10,-200],[1100,200]],"transform":[1,0,0,1,0,0]}],.01)
        self.assertTrue(source["pending"])
        self.assertFalse(source["faces"])


if __name__=="__main__":unittest.main()
