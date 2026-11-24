import json
from pathlib import Path
import tempfile
import unittest
import math
import subprocess
import sys
from verify_placement import verify_bundle
import test_validate_delivery as fixtures


class ProvenanceTests(unittest.TestCase):
    setUp=fixtures.GateTests.setUp
    tearDown=fixtures.GateTests.tearDown
    change_report=fixtures.GateTests.change_report
    run_gate=fixtures.GateTests.run_gate

    def test_real_cli_adapter_verifier_gate_pipeline(self):
        scripts=Path(__file__).resolve().parents[1]
        self.save("source-native.json",[{"handle":"W","type":"TCH_WALL","grips":[[0,-60],[1000,-60],[500,-60]],"bbox":[[0,-120],[1000,0]]}])
        native={"drawing_sha256":self.dwg["sha256"],"errors":[],"blocks":{"*Model_Space":[{"h":"A","type":"INSERT","layer":"EQUIP-插座","block":"socket","bbox":[[100,0],[200,50]]}],"socket":[{"h":"ARC","type":"ARC","start":[100,0],"end":[200,0],"mid":[150,50],"center":[150,0],"sweep":math.pi}]}}
        self.m["readback"]=self.save("native.json",native)
        self.save("geometry-config.json",{"drawing_sha256":self.dwg["sha256"],"source_drawings":{"source":self.src["sha256"]},"tolerance":.01,"floors":[{"id":"F","region":[[-10,-200],[1100,1000]]}],"sheets":[{"id":"S","floor":"F","region":[[-10,-200],[1100,1000]]}],"profiles":[{"layer":"EQUIP-插座","kind":"socket","extractor":"semicircle"}]})
        def run(script,*args):
            r=subprocess.run([sys.executable,str(scripts/script),*map(str,args)],capture_output=True,text=True,encoding="utf8")
            self.assertEqual(r.returncode,0,r.stdout+r.stderr)
        run("build_geometry_inputs.py","--source-native",self.p/"source-native.json","--saved-native",self.p/"native.json","--config",self.p/"geometry-config.json","--output",self.p/"normalized")
        geo=json.loads((self.p/"normalized/source-geometry.json").read_text("utf8"));self.m["geometry_source"]=self.save("geometry-source.json",geo)
        actual=json.loads((self.p/"normalized/actual-geometry.json").read_text("utf8"));actual["instances"][0].update(requirement_id="R",room="Room")
        actual["source_geometry_sha256"]=self.m["geometry_source"]["sha256"]
        self.m["actual"]=self.save("actual.json",actual)
        self.save("manifest.json",self.m)
        from validate_delivery import bound_inputs
        inputs,_=bound_inputs(self.p/"manifest.json")
        for key in fixtures.CORE_CHECKS:
            def update(r):
                r["inputs"]=inputs;r["points"][0]["id"]="A"
            self.change_report(key,update)
        self.save("manifest.json",self.m)
        run("verify_placement.py","--source",self.p/"geometry-source.json","--actual",self.p/"actual.json","--manifest",self.p/"manifest.json","--tolerance",".01","--report",self.p/"geometry-final.json")
        report=json.loads((self.p/"geometry-final.json").read_text("utf8"))
        self.m["checks"]["geometry"]=self.save("geometry-final.json",report)
        self.save("manifest.json",self.m)
        run("validate_delivery.py","--manifest",self.p/"manifest.json","--report",self.p/"release.json")
        self.assertTrue(json.loads((self.p/"release.json").read_text("utf8"))["reviewDraftReady"])
    def test_geometry_report_computes_actual_hash_after_file_is_written(self):
        self.save("manifest.json",self.m)
        report=verify_bundle(self.p/"geometry-source.json",self.p/"actual.json",self.p/"manifest.json",.01)
        self.assertEqual(report["inputs"]["actual"],self.m["actual"]["sha256"])
        self.assertEqual(report["inputs"]["geometry_source"],self.m["geometry_source"]["sha256"])

    def test_wrong_geometry_cli_file_is_rejected(self):
        self.save("manifest.json",self.m)
        self.save("other-geometry.json",{"faces":[]})
        report=verify_bundle(self.p/"other-geometry.json",self.p/"actual.json",self.p/"manifest.json",.01)
        self.assertFalse(report["passed"])
        self.assertIn("geometry input does not match manifest",str(report["errors"]).lower())


if __name__=="__main__":unittest.main()
