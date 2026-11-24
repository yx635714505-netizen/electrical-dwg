import copy
import hashlib
import json
from pathlib import Path
import tempfile
import struct
import zlib
import unittest
from validate_delivery import validate_delivery, CORE_CHECKS


class GateTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.p=Path(self.tmp.name)
        def save(name,obj):
            p=self.p/name
            p.write_text(json.dumps(obj),"utf8")
            return {"path":name,"sha256":hashlib.sha256(p.read_bytes()).hexdigest()}
        self.save=save
        self.dwg=self.save("drawing.dwg",{"test":"bytes"})
        self.src=self.save("source.dwg",{"source":"bytes"})
        self.geo_cfg=self.save("geometry-config.json",{"project":"source mappings"})
        self.geo=self.save("geometry-source.json",{"faces":[],"openings":[],"obstacles":[],
            "provenance":{"native_source":self.src,"config":self.geo_cfg,"source_drawings":{"source":self.src["sha256"]}}})
        self.native=self.save("native.json",{"drawing_sha256":self.dwg["sha256"],
            "errors":[], "blocks":{"*Model_Space":[{"h":"A","type":"INSERT","layer":"EQUIP-插座","bbox":[[0,0],[10,10]]}]}})
        self.expected=self.save("expected.json",{"basis":{"source":self.src["sha256"]},
            "requirements":[{"id":"R","sheet":"S","floor":"F","room":"Room","kind":"socket","quantity":1,"basis":["source:wall"]}]})
        self.actual=self.save("actual.json",{"drawing_sha256":self.dwg["sha256"],"readback_sha256":self.native["sha256"],"source_geometry_sha256":self.geo["sha256"],
            "instances":[{"id":"P","requirement_id":"R","sheet":"S","floor":"F","room":"Room","kind":"socket","handles":["A"]}]})
        def chunk(kind,data):return struct.pack(">I",len(data))+kind+data+struct.pack(">I",zlib.crc32(kind+data)&0xffffffff)
        png=b"\x89PNG\r\n\x1a\n"+chunk(b"IHDR",struct.pack(">IIBBBBB",20,20,8,2,0,0,0))+chunk(b"IDAT",zlib.compress((b"\x00"+b"\xff"*60)*20))+chunk(b"IEND",b"")
        (self.p/"image.png").write_bytes(png)
        self.image={"path":"image.png","sha256":hashlib.sha256(png).hexdigest()}
        self.m={"schema":1,"mode":"review","drawing":self.dwg,"sources":{"source":self.src},
                "rules":{"r":self.save("rule.md",{"v":1})},
                "readback":self.native,"expected":self.expected,"actual":self.actual,"geometry_source":self.geo,
                "sheets":["S"],"checks":{},"engineering":{"status":"pending","items":["equipment"]}}
        self.inputs={"drawing":self.dwg["sha256"],"source":self.src["sha256"],
                     "readback":self.native["sha256"],"expected":self.expected["sha256"],
                     "actual":self.actual["sha256"],"geometry_source":self.geo["sha256"],"geometry-native":self.src["sha256"],"geometry-config":self.geo_cfg["sha256"],"rule:r":self.m["rules"]["r"]["sha256"]}
        for key in CORE_CHECKS:
            report={"status":"passed","drawing_sha256":self.dwg["sha256"],"inputs":self.inputs,"acceptanceEligible":True,
                    "evidence":"Performed check","points":[{"id":"P","status":"passed","evidence":"actual native geometry"}]}
            if key=="visual":
                report.update(artifacts={"render":self.image},
                    pages=[{"sheet":"S","status":"passed","evidence":{"artifact":"render","page":1,"region":[0,0,10,10]}}],
                    points=[{"id":"P","status":"passed","evidence":{"artifact":"render","page":1,"region":[0,0,5,5]}}])
            self.m["checks"][key]=self.save(key+".json",report)

    def tearDown(self):self.tmp.cleanup()

    def run_gate(self):
        self.save("manifest.json",self.m)
        return validate_delivery(self.p/"manifest.json")

    def change_report(self,name,edit):
        ref=self.m["checks"][name]
        report=json.loads((self.p/ref["path"]).read_text("utf8"))
        edit(report)
        self.m["checks"][name]=self.save(ref["path"],report)

    def test_complete_review_evidence_can_pass_with_engineering_pending(self):
        r=self.run_gate()
        self.assertTrue(r["reviewDraftReady"])
        self.assertFalse(r["constructionReady"])

    def test_missing_mandatory_geometry_check_blocks_review(self):
        del self.m["checks"]["geometry"]
        self.assertFalse(self.run_gate()["reviewDraftReady"])

    def test_source_name_cannot_override_reserved_drawing_binding(self):
        self.m["sources"]={"drawing":self.src}
        self.assertFalse(self.run_gate()["reviewDraftReady"])

    def test_explicit_failed_engineering_is_not_accepted_as_pending(self):
        self.m["engineering"]={"status":"failed","items":["known incorrect circuit"]}
        self.assertFalse(self.run_gate()["reviewDraftReady"])

    def test_unknown_status_and_empty_points_cannot_pass(self):
        self.change_report("geometry",lambda r:r.update(status="passed",points=[]))
        self.assertFalse(self.run_gate()["reviewDraftReady"])

    def test_passed_heading_cannot_hide_nonempty_error_list(self):
        self.change_report("geometry",lambda r:r.update(errors=["wall unsupported"]))
        self.assertFalse(self.run_gate()["reviewDraftReady"])

    def test_support_only_geometry_report_does_not_release_drawing(self):
        self.change_report("geometry",lambda r:r.update(acceptanceEligible=False))
        self.assertFalse(self.run_gate()["reviewDraftReady"])

    def test_engineering_pass_heading_cannot_hide_explicit_failure(self):
        self.m["engineering"]={"status":"passed","items":[],"report":self.save("engineering.json",{
            "status":"passed","passed":False,"inputs":self.inputs,"drawing_sha256":self.dwg["sha256"],
            "evidence":"explicit review","errors":[],"pending":[]})}
        self.assertFalse(self.run_gate()["reviewDraftReady"])

    def test_construction_requires_engineering_report_not_a_boolean(self):
        self.m["engineering"]={"status":"passed","items":[]}
        self.m["mode"]="construction"
        self.assertFalse(self.run_gate()["constructionReady"])

    def test_invalid_engineering_pass_claim_also_blocks_review_label(self):
        self.m["engineering"]={"status":"passed","items":[]}
        self.assertFalse(self.run_gate()["reviewDraftReady"])

    def test_stale_final_dwg_hash_blocks_all_release(self):
        (self.p/"drawing.dwg").write_bytes(b"changed")
        self.assertFalse(self.run_gate()["reviewDraftReady"])

    def test_report_hash_tampering_is_detected(self):
        (self.p/"geometry.json").write_bytes(b"changed")
        self.assertFalse(self.run_gate()["reviewDraftReady"])

    def test_report_from_old_actual_inventory_is_blocked(self):
        self.change_report("geometry",lambda r:r.update(inputs=dict(self.inputs,actual="0"*64)))
        self.assertFalse(self.run_gate()["reviewDraftReady"])

    def test_extra_native_instance_cannot_be_left_unmapped(self):
        native=json.loads((self.p/"native.json").read_text("utf8"))
        native["blocks"]["*Model_Space"].append({"h":"B","type":"INSERT","layer":"EQUIP-开关"})
        self.m["readback"]=self.save("native.json",native)
        self.assertFalse(self.run_gate()["reviewDraftReady"])

    def test_unsupported_native_equipment_type_is_not_ignored(self):
        native=json.loads((self.p/"native.json").read_text("utf8"))
        native["blocks"]["*Model_Space"].append({"h":"B","type":"TCH_EQUIPMENT","layer":"EQUIP-开关"})
        self.m["readback"]=self.save("native.json",native)
        self.assertFalse(self.run_gate()["coverage"]["passed"])

    def test_native_proxy_entity_cannot_receive_release(self):
        native=json.loads((self.p/"native.json").read_text("utf8"))
        native["blocks"]["unresolved"]=[{"h":"Z","type":"ACAD_PROXY_ENTITY","layer":"0"}]
        self.m["readback"]=self.save("native.json",native)
        self.assertFalse(self.run_gate()["reviewDraftReady"])

    def test_missing_requirement_or_wrong_room_blocks_coverage(self):
        actual=json.loads((self.p/"actual.json").read_text("utf8"))
        actual["instances"][0]["room"]="other"
        self.m["actual"]=self.save("actual.json",actual)
        self.assertFalse(self.run_gate()["coverage"]["passed"])

    def test_duplicate_actual_handles_are_blocked(self):
        actual=json.loads((self.p/"actual.json").read_text("utf8"))
        actual["instances"].append(dict(actual["instances"][0],id="Q"))
        self.m["actual"]=self.save("actual.json",actual)
        self.assertFalse(self.run_gate()["coverage"]["passed"])

    def test_old_or_missing_visual_region_blocks_review(self):
        self.change_report("visual",lambda r:r["points"][0].update(evidence={"artifact":"render","page":1}))
        self.assertFalse(self.run_gate()["reviewDraftReady"])

    def test_hashed_nonimage_cannot_prove_visual_review(self):
        self.image=self.save("image.png",{"not":"an image"})
        self.change_report("visual",lambda r:r.update(artifacts={"render":self.image}))
        self.assertFalse(self.run_gate()["reviewDraftReady"])

    def test_out_of_image_region_cannot_prove_point_review(self):
        self.change_report("visual",lambda r:r["points"][0]["evidence"].update(region=[0,0,100,100]))
        self.assertFalse(self.run_gate()["reviewDraftReady"])

    def test_png_does_not_have_arbitrary_page_numbers(self):
        self.change_report("visual",lambda r:r["points"][0]["evidence"].update(page=200))
        self.assertFalse(self.run_gate()["reviewDraftReady"])

    def test_missing_page_visual_review_blocks_release(self):
        self.m["sheets"].append("S2")
        self.assertFalse(self.run_gate()["reviewDraftReady"])

    def test_visual_image_changed_after_review_is_blocked(self):
        (self.p/"image.png").write_bytes(b"changed")
        self.assertFalse(self.run_gate()["reviewDraftReady"])

    def test_does_not_confuse_review_draft_with_construction(self):
        self.m["mode"]="construction"
        r=self.run_gate()
        self.assertFalse(r["passed"])
        self.assertTrue(r["reviewDraftReady"])

    def test_unverified_source_inventory_is_pending(self):
        expected=json.loads((self.p/"expected.json").read_text("utf8"))
        expected["basis"]={}
        self.m["expected"]=self.save("expected.json",expected)
        self.assertFalse(self.run_gate()["coverage"]["passed"])

    def test_missing_manifest_or_bad_json_returns_failed_report(self):
        (self.p/"bad.json").write_text("{}","utf8")
        self.assertFalse(validate_delivery(self.p/"bad.json")["passed"])


if __name__=="__main__":unittest.main()
