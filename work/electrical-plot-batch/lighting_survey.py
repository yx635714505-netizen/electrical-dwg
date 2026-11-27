"""照明专项。建筑调查独立于布点；所有坐标为楼层局部毫米。"""
from collections import Counter
from hashlib import sha256
import json
import math
from pathlib import Path

from review_preflight import inside_space, on_segment

LAMPS = {"LIGHT", "WETLIGHT", "WALLLIGHT"}
SWITCHES = {"SW", "SW2", "SW3", "DUAL"}


def inside(p, ring, edge=True):
    if len(ring) < 3 or not all(len(q) == 2 and all(map(math.isfinite, q)) for q in ring):
        raise ValueError("建筑调查多边形缺少有效顶点")
    if any(on_segment(p, pair) for pair in zip(ring, ring[1:] + ring[:1])):
        return edge
    return inside_space(p, ring)


def contains(p, part):
    return inside(p, part["boundary"]) and not any(inside(p, h) for h in part.get("holes", []))


def path_samples(path, rings):
    """在每个多边形交点之间取点，凹形走道两端在界内也可能中途穿墙。"""
    yield from path
    for a, b in zip(path, path[1:]):
        dx, dy = b[0]-a[0], b[1]-a[1]
        cuts = {0., 1.}
        for ring in rings:
            for p, q in zip(ring, ring[1:]+ring[:1]):
                ex, ey = q[0]-p[0], q[1]-p[1]
                den = dx*ey-dy*ex
                if abs(den) < 1e-9:
                    continue
                px, py = p[0]-a[0], p[1]-a[1]
                t, u = (px*ey-py*ex)/den, (px*dy-py*dx)/den
                if 0<t<1 and 0<=u<=1:
                    cuts.add(t)
        ordered = sorted(cuts)
        for start,end in zip(ordered,ordered[1:]):
            t = (start+end)/2
            yield [a[0]+t*dx, a[1]+t*dy]


def fixture_kinds(part):
    """生成器先按本段建筑调查选型，随后在有效范围内布置。"""
    if not part.get("source"):
        raise ValueError("缺少来源图页、构件或用户确认依据")
    condition = part["condition"]
    if condition == "covered":
        return {"LIGHT", "WETLIGHT"}
    if condition in {"open", "entranceWall"} and part.get("walls"):
        return {"WALLLIGHT"}
    if condition == "passage":
        return {"LIGHT", "WETLIGHT"}
    if condition == "unknown":
        raise ValueError("顶板条件待核；已核实的壁灯安装面仅作暂定")
    raise ValueError("缺少已核实的顶板条件或露天段安装面")


def entry_candidate(entry, width):
    """在此入口独立量得的净墙段中选可容纳整块面板的首选段。"""
    if not entry.get("source") or len(entry["route"]) < 2 or entry["operateIn"] not in entry["route"][-2:]:
        raise ValueError("入口缺少建筑依据、日常来向或操作侧")
    if not math.isfinite(width) or width <= 0:
        raise ValueError("面板实宽无效")
    origin = entry["entryPoint"]
    choices = []
    for i, seg in enumerate(entry["faces"]):
        a, b = seg["ends"]
        length = math.dist(a, b)
        if length < width:
            continue
        n = seg["normal"]
        t = [(b[k]-a[k])/length for k in (0, 1)]
        if not seg.get("wall") or abs(t[0]*math.cos(n)+t[1]*math.sin(n)) > .001:
            raise ValueError("净墙段法向或来源异常")
        if seg.get("priority", 0) and not seg.get("obstacle"):
            raise ValueError("备选墙段缺少首选点的遮挡依据")
        along = sum((origin[k]-a[k])*t[k] for k in (0, 1))
        at = max(width/2, min(length-width/2, along))
        p = [a[k]+at*t[k] for k in (0, 1)]
        choices.append((seg.get("priority", 0), math.dist(p, origin), i, p))
    if not choices:
        raise ValueError("入口没有足宽可达墙段")
    _, _, i, p = min(choices)
    if entry.get("doorType") == "single":
        from entry_and_leader import latch_side
        door = entry.get("swing", {})
        if not door.get("leafSource") or not (latch_side(p, door) or entry.get("fallbackObstacle")):
            raise ValueError("单扇门开关缺少门扇依据或落在铰侧")
    return entry["faces"][i], p


def required_areas(design, sheet):
    names = set()
    for z in design.get("lightingZones", {}).get(sheet["number"], []):
        if "outdoorMount" in z or any(word in z["name"] for word in ("阳台", "露台", "露天", "过道", "走廊", "过廊")):
            names.add(z["name"])
    ctx = design["switchSpaces"][str(sheet["floor"])]
    names.update(n for n, v in ctx["spaces"].items() if v.get("use") == "circulation")
    return names


def area_errors(design, sheet, area, devices):
    """逐区覆盖与入口复核；跨层枚举由 survey_errors 负责。"""
    name = area["name"]
    ctx = design["switchSpaces"][str(sheet["floor"])]
    zones = design["lightingZones"][sheet["number"]]
    selected = [z for z in zones if z["name"] in area.get("zones", [name])]
    bounds = [z["boundary"] for z in selected]
    rooms = ctx["lampSpaces"]
    lamps = [d for d in devices if d["kind"] in LAMPS and rooms.get(d["id"]) == name]
    issues = []
    parts = area["parts"]
    if not parts or not area["entries"]:
        raise ValueError("缺少逐段照明或日常入口调查")
    counted = Counter()
    for part in parts:
        try:
            accepted = fixture_kinds(part)
        except ValueError as exc:
            issues.append(str(exc))
            continue
        if part["condition"] == "passage":
            path = part.get("path", [])
            samples = list(path_samples(path, bounds+[part["boundary"]]+part.get("holes", [])))
            if len(path) < 2 or not all(contains(p, part) for p in samples):
                raise ValueError("过道缺少本段入口至尽端或转折的通行依据")
            if any(not any(inside(p, ring) for ring in bounds) for p in samples):
                issues.append("设计过道边界漏掉通行段或转折")
        if part["condition"] == "covered" and not any(z.get("outdoorMount", {}).get("slabs") for z in selected):
            issues.append("布置时缺少本区顶板判定")
        local = [d for d in lamps if contains(d["p"], part)]
        usable = []
        for d in local:
            if d["kind"] not in accepted:
                issues.append(f"{d['id']} 灯型与{part['condition']}段的建筑依据不符")
                continue
            if d["kind"] == "WALLLIGHT" and not any(
                w.get("source") and on_segment(d["p"], w["ends"]) for w in part["walls"]
            ):
                issues.append(f"{d['id']} 壁灯偏离实际墙柱安装面")
                continue
            if part["condition"] == "covered" and not inside(d["p"], part["boundary"], edge=False):
                issues.append(f"{d['id']} 灯位在板边，须核实安装范围")
                continue
            usable.append(d)
        minimum = part["minimum"]
        if type(minimum) is not int or minimum < 1:
            raise ValueError("缺少本段应设灯数")
        if len(usable) < minimum:
            issues.append(f"{part['condition']}段应设至少{minimum}盏，合格{len(usable)}盏")
        counted.update(d["id"] for d in usable)
    for d in lamps:
        if counted[d["id"]] != 1:
            issues.append(f"{d['id']} 未唯一对应已核实的安装段")
    issues.extend(entry_errors(name, area["entries"], devices, ctx, {d["id"] for d in lamps}))
    return list(dict.fromkeys(issues))


def entry_errors(name, entries, devices, ctx, linked):
    controls = [d for d in devices if d.get("switchIntent", {}).get("route", [None])[-1] == name
                and d["switchIntent"]["role"] != "bedside"]
    issues = []
    for entry in entries:
        candidates = [d for d in controls if d["switchIntent"]["route"][-2:] == entry["route"][-2:]]
        for device in candidates:
            access = ctx.get("access", {}).get(device["switchIntent"]["access"], {})
            if access.get("kind") == "door" and (ctx.get("requireDoorEvidence") or entry.get("doorType")):
                kind = entry.get("doorType")
                if kind not in {"single", "double", "sliding", "folding", "other"}:
                    issues.append(f"{device['id']} 门型和操作侧缺少原图依据")
                elif kind != "single" and not entry.get("approachNote"):
                    issues.append(f"{device['id']} 该门型缺日常通行扇或操作侧依据")
                elif kind == "single":
                    from entry_and_leader import latch_side
                    door = entry.get("swing", {})
                    if not all(door.get(k) for k in ("hinge","latch","openLeaf","leafSource")):
                        issues.append(f"{device['id']} 缺门洞、铰侧或开启扇来源")
                    elif not latch_side(device["p"],door) and not entry.get("fallbackObstacle"):
                        issues.append(f"{device['id']} 实际面板位于铰侧且无执手侧遮挡依据")
        if not candidates:
            issues.append(f"开关来向错误或缺失，应从{entry['route'][-2]}进入{name}")
        elif not any(fits_entry(d, entry) for d in candidates):
            issues.append("面板偏离入口首选可用墙段或朝向错误")
    for d in controls:
        intent = d["switchIntent"]
        operating = intent.get("operateIn") or next((v["space"] for v in ctx["spans"] if intent["access"] in v["at"]), None)
        if not any(intent["route"][-2:] == a["route"][-2:] and a["operateIn"] == operating
                   and fits_entry(d, a) for a in entries):
            issues.append(f"{d['id']} 缺少对应的可达入口或操作侧错误")
        if not linked.intersection(intent["lights"]):
            issues.append(f"{d['id']} 未控制本区灯组")
    return list(dict.fromkeys(issues))


def fits_entry(d, entry):
    width = d["switchIntent"]["width"]
    seg, _ = entry_candidate(entry, width)
    n = seg["normal"]
    if (d.get("support") and d["support"] != seg["wall"]) or math.cos(d["normal"]-n) < .999:
        return False
    p = d["p"]
    tangent = [-math.sin(n), math.cos(n)]
    return all(on_segment([p[k]+side*width/2*tangent[k] for k in (0,1)], seg["ends"]) for side in (-1,1))


def read_basis(design_path, design):
    path = Path(design_path).with_name("lighting_survey.json")
    if not path.is_file():
        raise ValueError("缺少布点前独立量取的 lighting_survey.json")
    data = path.read_bytes()
    if sha256(data).hexdigest() != design.get("lightingSurveySHA256"):
        raise ValueError("照明调查与组装采用的版本哈希不一致")
    survey = json.loads(data.decode("utf-8-sig"))
    source_name = survey.get("architectureFile") or design.get("sources", {}).get("ar")
    if not source_name:
        raise ValueError("缺少源建筑 DWG 路径")
    source = path.parent / source_name
    if sha256(source.read_bytes()).hexdigest() != survey["architectureSHA256"]:
        raise ValueError("照明调查与本次建筑底图哈希不一致")
    return survey


def open_plan_errors(floor, devices):
    """核对建筑底图独立圈定的各使用区，设计清单及原生回读共用。"""
    if not str(floor.get("openPlanReview") or "").strip() or not isinstance(floor.get("openPlanParts"), list):
        return ["缺少大开间逐层调查或分段清单"]
    issues = []
    assigned = set()
    names = set()
    for part in floor["openPlanParts"]:
        name = part["name"]
        ring = part["boundary"]
        minimum = part["minimum"]
        if not name or name in names or not part.get("source") or type(minimum) is not int or minimum < 1:
            raise ValueError("大开间分段名称、建筑依据或最低灯数无效")
        names.add(name)
        if len(ring) < 3:
            raise ValueError(f"{name} 缺少建筑净空边界")
        found = {d["id"] for d in devices if d["kind"] in LAMPS
                 and inside(d["p"][:2], ring, edge=False)
                 and not any(inside(d["p"][:2], hole) for hole in part.get("holes", []))}
        if len(found) < minimum:
            issues.append(f"{name} 应有至少{minimum}盏，本段实有{len(found)}盏")
        if assigned.intersection(found):
            issues.append(f"{name} 与另一使用区重复计灯")
        assigned.update(found)
    return issues


def survey_errors(design, survey, devices):
    sheets = {s["number"]:s for s in design["sheets"] if s["kind"]=="lighting"}
    if set(survey["sheets"]) != set(sheets):
        raise ValueError("独立照明调查未覆盖全部照明图页")
    errors = []
    for key, sheet in sheets.items():
        floor = survey["sheets"][key]
        rows = floor["areas"]
        local = [d for d in devices if d["sheet"] == key]
        if design.get("requireOpenPlanReview") or "openPlanParts" in floor:
            try:
                issues = open_plan_errors(floor, local)
            except (KeyError, ValueError, TypeError, IndexError) as exc:
                issues = [f"建筑分段依据无效 {exc}"]
            errors.extend(f"{key} {issue}" for issue in issues)
        names = [a["name"] for a in rows]
        missing = required_areas(design, sheet)-set(names)
        if missing or len(names) != len(set(names)):
            errors.append(f"{key} 同类区域漏列或重复 {sorted(missing)}")
        for area in rows:
            try:
                issues = area_errors(design, sheet, area, local)
            except (KeyError, ValueError, TypeError, IndexError) as exc:
                issues = [f"依据不完整 {exc}"]
            errors.extend(f"{key} {area['name']} {v}" for v in issues)
        ctx = design["switchSpaces"][str(sheet["floor"])]
        ordinary = floor.get("otherEntries", {})
        active = {d["switchIntent"]["route"][-1] for d in local if d.get("switchIntent")
                  and d["switchIntent"]["role"] != "bedside"}
        for room in sorted(active - set(names) - ordinary.keys()):
            errors.append(f"{key} {room} 漏列日常入口调查")
        for room, entries in ordinary.items():
            lamps = {i for i, r in ctx["lampSpaces"].items() if r == room}
            if not entries or room in names:
                errors.append(f"{key} {room} 入口清单为空或重复")
            else:
                errors.extend(f"{key} {room} {v}" for v in entry_errors(room, entries, local, ctx, lamps))
    return errors


def lamp_copy_errors(design):
    """新组装前核对实际原件标识和插块坐标；增量编辑以保存后实体为准。"""
    if "edits" in design or "priorHash" in design:
        return []
    copies = {}
    for job in design["jobs"]:
        if job.get("op") == "copy" and job.get("tag"):
            copies.setdefault(job["tag"], []).append(job)
    errors = []
    for d in design["devices"]:
        if d["kind"] not in LAMPS:
            continue
        tag = f"dev-{d['sheet']}-{d['id']}"
        cmds = copies.get(tag, [])
        if len(cmds) != 1 or not d.get("sourceHandle") or cmds[0].get("handles") != [d["sourceHandle"]]:
            errors.append(f"{tag} 缺少对应灯具原件或实际插块指令不符")
        elif math.dist(cmds[0]["p"][:2], d["world"][:2]) > .5:
            errors.append(f"{tag} 灯位与实际插块指令不符")
    return errors


def native_devices(design, native, catalog, handles):
    """由保存的块名、变换和实测块内安装点还原位置，保留设计的灯组与操作意图作对照。"""
    if native.get("errors"):
        raise ValueError("原生回读存在错误")
    model = {e["h"]: e for e in native["blocks"]["*Model_Space"]}
    pages = {s["number"]:s for s in design["sheets"] if s["kind"] == "lighting"}
    observations = []
    used = set()
    for d in design["devices"]:
        if d["sheet"] not in pages or d["kind"] not in LAMPS | SWITCHES:
            continue
        h = handles["dev-" + d["sheet"] + "-" + d["id"]]
        entity = model[h]
        if h in used or entity["type"] != "INSERT":
            raise ValueError(f"{d['id']} 原生设备句柄重复或类型异常")
        used.add(h)
        block = entity["block"]
        symbol = catalog[block]
        if symbol["kind"] != d["kind"]:
            raise ValueError(f"{d['id']} 保存的灯具或面板原件与设计不同")
        base = native["blockOrigins"][block]
        sx, sy = entity["scale"][:2]
        angle = entity["angle"]
        cs, sn = math.cos(angle), math.sin(angle)
        x, y = ((v-b)*k for v,b,k in zip(symbol["anchor"], base, (sx,sy)))
        pos = entity["pos"]
        world = [pos[0]+cs*x-sn*y, pos[1]+sn*x+cs*y]
        offset = design["switchSpaces"][str(d["floor"])]["sheetOrigins"][d["sheet"]]
        point = [world[i]-offset[i] for i in (0,1)]
        if math.dist(point,d["p"]) > .5:
            raise ValueError(f"{d['id']} 原生安装点与预检位置不同")
        item = dict(d, p=point, kind=symbol["kind"])
        if item["kind"] in SWITCHES:
            nx, ny = symbol["normal"]
            # Normal to a transformed support edge (including mirrored inserts).
            item["normal"] = angle + math.atan2(ny/sy, nx/sx)
            if not math.isclose(math.hypot(nx,ny),1,abs_tol=.001):
                raise ValueError(f"{block} 缺少样板单位法向")
            width = symbol["width"] * math.hypot(ny*sx,nx*sy)
            if not math.isfinite(width) or abs(width-d["switchIntent"]["width"]) > .5:
                raise ValueError(f"{d['id']} 原生面板安装宽度与样板选点宽度不符")
            item["switchIntent"] = dict(d["switchIntent"],width=width)
        observations.append(item)
    actual_layers = {model[h]["layer"] for h in used}
    for e in model.values():
        if e.get("type") != "INSERT" or e.get("block") not in catalog or e["h"] in used:
            continue
        if e["layer"] not in actual_layers:
            continue
        x, y = e["pos"][:2]
        if any(p["x"]<=x<=p["x"]+p["w"] and p["y"]<=y<=p["y"]+p["h"] for p in pages.values()):
            raise ValueError(f"照明图存在未列入点位清单的实体 {e['h']}")
    return observations


def saved_errors(path, design, plan, native_path, native):
    if not any(s["kind"] == "lighting" for s in design["sheets"]):
        return []
    try:
        basis = read_basis(path, design)
        spec = plan["lightingReadback"]
        handles = spec.get("handles")
        if handles is None:
            trace = json.loads(native_path.with_name("clone_trace.json").read_text(encoding="utf-8-sig"))
            handles = {t["tag"]:t["newHandles"][0] for t in trace if (t.get("tag") or "").startswith("dev-")}
        actual = native_devices(design, native, spec["symbols"], handles)
        return survey_errors(design, basis, actual)
    except (KeyError, ValueError, TypeError, IndexError, OSError, ZeroDivisionError) as exc:
        return [f"保存后照明依据或实体校核失败 {exc}"]
