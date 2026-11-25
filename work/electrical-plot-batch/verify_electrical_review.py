"""以项目原生回读核对底图、图例及首层进线。异常退出码为 1。"""
import argparse
import json
import math
from pathlib import Path

from verify_background_cleanup import verify as check_backgrounds
from verify_title_fields import verify as check_title_fields


def bounds(entity):
    a, b = entity["bbox"]
    return a[0], a[1], b[0], b[1]


def on_box(point, box, tol=.25):
    x, y = point[:2]
    l, b, r, t = box
    return (l-tol <= x <= r+tol and b-tol <= y <= t+tol
            and min(abs(x-l), abs(x-r), abs(y-b), abs(y-t)) <= tol)


def hits_box(start, end, box):
    lo, hi = 0., 1.
    for a, b, lower, upper in zip(start[:2], end[:2], box[:2], box[2:]):
        if abs(b-a) < 1e-9:
            if not lower <= a <= upper:
                return False
        else:
            u, v = sorted(((lower-a)/(b-a), (upper-a)/(b-a)))
            lo, hi = max(lo, u), min(hi, v)
    return lo <= hi


def service_errors(model, spec):
    errors = []
    am, meb = (bounds(model[spec[k]]) for k in ("am", "meb"))
    feed, arrow, bond = (model[spec[k]] for k in ("feed", "arrow", "bond"))
    points = feed["vertices"]
    tip = arrow["vertices"][spec["tipIndex"]]
    # 用已核实的室外进户目标校验箭头位置，允许多段线反向存储。
    if math.dist(points[0][:2], tip[:2]) < math.dist(points[-1][:2], tip[:2]):
        points = points[::-1]
    if not on_box(points[0], am) or math.dist(points[-1][:2], tip[:2]) > .25:
        errors.append("总箱端点或室外箭头断开")
    if math.dist(tip[:2], spec["outsideTip"][:2]) > .25:
        errors.append("室外箭头偏离项目确认的进户位置")
    if model[spec["caption"]].get("text") != "接电力局市政电源":
        errors.append("市政电源标注不符")
    for obj in (feed, arrow):
        if (obj["layer"] != spec["powerLayer"] or obj.get("type") != "LWPOLYLINE"
                or spec["width"] <= 0 or abs(obj.get("width", -1)-spec["width"]) > .01):
            errors.append("动力线图层或统一线宽不符")
    if any(hits_box(a,b,meb) for a,b in zip(points,points[1:])):
        errors.append("动力线接触或穿过 MEB 箱体")
    p, q = bond["vertices"][0], bond["vertices"][-1]
    if (bond["layer"] != spec["bondLayer"] or bond["layer"] == feed["layer"]
            or not ((on_box(p,meb) and on_box(q,am)) or (on_box(q,meb) and on_box(p,am)))):
        errors.append("MEB 至总箱保护联结的图层或端点不符")
    return errors


def check(native, design, plan):
    if native.get("errors"):
        raise ValueError("原生回读存在错误")
    model = {e["h"]:e for e in native["blocks"]["*Model_Space"]}
    backgrounds = plan["backgrounds"]
    actual = {e["block"] for e in model.values() if e["type"]=="INSERT" and e["layer"] in plan["backgroundLayers"]}
    listed = {b["base"] for b in backgrounds}
    if not actual or actual != listed:
        raise ValueError(f"底图覆盖不一致 {actual ^ listed}")
    issues = {"底图":check_backgrounds(native,backgrounds), "进线":[], "图例":[],
              "图签":check_title_fields(native, design["sheets"], plan.get("titleFields", {}))}
    for service in plan["services"]:
        issues["进线"].extend(service_errors(model,service))
    if not plan["services"]:
        raise ValueError("缺少首层进线核对依据")
    expected = {s["number"] for s in design["sheets"] if s["kind"]=="socket"}
    if set(plan["legends"]) != expected:
        raise ValueError("插座图例核对页与应出图清单不符")
    sheets = {s["number"]:s for s in design["sheets"]}
    for sheet, spec in plan["legends"].items():
        page = sheets[sheet]
        for h in spec["legend"] + spec["protected"]:
            l,b,r,t = bounds(model[h])
            if not (page["x"] <= (l+r)/2 <= page["x"]+page["w"]
                    and page["y"] <= (b+t)/2 <= page["y"]+page["h"]):
                raise ValueError(sheet+" 图例或避让对象取自其他页")
        areas = spec["protected"]
        if not areas or not spec["legend"]:
            raise ValueError(sheet+" 缺少图例或避让范围")
        for handle in spec["legend"]:
            l,b,r,t = bounds(model[handle])
            for other in areas:
                L,B,R,T = bounds(model[other])
                if max(l,L)<=min(r,R) and max(b,B)<=min(t,T):
                    issues["图例"].append(f"{sheet} 图例 {handle} 进入避让区 {other}，须移位或细化实际轮廓重新校核")
    return issues


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ("native","design","plan"):
        parser.add_argument(arg,type=Path)
    args=parser.parse_args()
    load=lambda p:json.loads(p.read_text(encoding="utf-8-sig"))
    from lighting_survey import saved_errors
    native,design,plan = map(load, (args.native,args.design,args.plan))
    result=check(native,design,plan)
    result["照明区域与入口"]=saved_errors(args.design,design,plan,args.native,native)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    raise SystemExit(int(any(result.values())))
