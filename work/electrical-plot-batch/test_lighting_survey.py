"""照明建筑调查的通用预检与原生回读测试。"""
import json
import math
from pathlib import Path
import unittest

from lighting_survey import entry_candidate, fixture_kinds


def rect(x, y, X, Y):
    return [[x,y],[X,y],[X,Y],[x,Y]]


def part(source, shape, condition, **more):
    return dict(source=source, condition=condition, boundary=shape, minimum=1, **more)


def entry(route, operating, source, jamb, wall, a, b, normal):
    return dict(source=source, route=route, operateIn=operating, entryPoint=jamb,
                faces=[dict(wall=wall, ends=[a,b], normal=normal)])


class LightingSurveyTest(unittest.TestCase):
    def test_shared_preflight_and_saved_entity_gate(self):
        from hashlib import sha256
        from tempfile import TemporaryDirectory
        from review_preflight import check_architectural_lighting
        from lighting_survey import saved_errors
        with TemporaryDirectory() as tmp:
            folder=Path(tmp)
            dwg=folder/"ar.dwg"
            dwg.write_bytes(b"synthetic architecture for gate test")
            build=folder/"build.json"
            native_path=folder/"generated_native.json"
            sh=dict(number="E1",kind="lighting",floor=1,x=0,y=0,w=5000,h=5000)
            boundary=rect(0,0,2000,1200)
            door=entry(["厅","阳台"],"厅","开口A与墙W",[0,500],"W",[0,300],[0,700],0)
            area=dict(name="阳台",parts=[part("顶板A",boundary,"covered")],entries=[door])
            ctx=dict(spaces={"阳台":{"use":"阳台"}},lampSpaces={"L":"阳台"},sheetOrigins={"E1":[0,0]},
                     spans=[dict(space="厅",at=["A"])])
            lamp=dict(id="L",floor=1,sheet="E1",kind="LIGHT",p=[1000,600],world=[1000,600],sourceHandle="T")
            sw=dict(id="S",floor=1,sheet="E1",kind="SW",p=[0,500],normal=0,support="W",
                    switchIntent=dict(route=["厅","阳台"],operateIn="厅",access="A",role="shared",lights=["L"],width=100))
            zone=dict(name="阳台",boundary=boundary,outdoorMount=dict(slabs=[dict(source="顶板A",boundary=boundary)]))
            design=dict(sheets=[sh],sources={"ar":"ar.dwg"},lightingZones={"E1":[zone]},switchSpaces={"1":ctx},
                        devices=[lamp,sw],jobs=[dict(op="copy",tag="dev-E1-L",handles=["T"],p=[1000,600])])
            survey=dict(architectureSHA256=sha256(dwg.read_bytes()).hexdigest(),sheets={"E1":dict(areas=[area])})
            path=folder/"lighting_survey.json"
            def bind():
                path.write_text(json.dumps(survey),"utf8")
                design["lightingSurveySHA256"]=sha256(path.read_bytes()).hexdigest()
            self.assertTrue(check_architectural_lighting(build,design))
            bind()
            self.assertEqual(check_architectural_lighting(build,design),[])
            spec=dict(symbols={"lamp":dict(kind="LIGHT",anchor=[0,0]),
                               "panel":dict(kind="SW",anchor=[0,0],normal=[1,0],width=100)})
            spec["handles"]={"dev-E1-L":"a","dev-E1-S":"b"}
            model=[dict(h=h,type="INSERT",block=b,pos=p,layer="equipment",scale=[1,1,1],angle=0)
                   for h,b,p in [("a","lamp",[1000,600]),("b","panel",[0,500])]]
            native=dict(blocks={"*Model_Space":model},blockOrigins={b:[0,0,0] for b in spec["symbols"]})
            def saved():
                return saved_errors(build,design,{"lightingReadback":spec},native_path,native)
            self.assertEqual(saved(),[])
            model[1]["angle"]=math.pi
            self.assertTrue(saved())
            model[1]["angle"]=0
            model[0]["pos"]=[800,600]
            self.assertIn("安装点"," ".join(saved()))
            design["jobs"][0]["p"]=[800,600]
            self.assertIn("插块指令"," ".join(check_architectural_lighting(build,design)))
            design["jobs"][0]["p"]=[1000,600]
            path.write_text(path.read_text()+" ","utf8")
            self.assertIn("哈希"," ".join(check_architectural_lighting(build,design)))
            survey["sheets"]["E1"]["areas"]=[]
            bind()
            self.assertIn("漏列"," ".join(check_architectural_lighting(build,design)))
            dwg.write_bytes(b"changed source")
            self.assertIn("建筑底图哈希"," ".join(check_architectural_lighting(build,design)))

    def test_unknown_slab_and_narrow_pier(self):
        with self.assertRaisesRegex(ValueError,"待核"):
            fixture_kinds(dict(source="上层图缺失",condition="unknown",walls=[{"source":"墙"}]))
        with self.assertRaisesRegex(ValueError,"足宽"):
            entry_candidate(entry(["厅","阳台"],"厅","开口",[0,50],"W",[0,0],[0,100],0),250)


if __name__ == "__main__":
    unittest.main()
