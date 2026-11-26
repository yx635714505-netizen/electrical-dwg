"""审核稿成图前的样板校准复用与楼层覆盖检查。"""
import argparse
from collections import Counter, defaultdict
from hashlib import sha256
import json
import math
from pathlib import Path


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def socket_calibration(sample_dir, cache):
    for name, expected in cache["sampleSHA256"].items():
        actual = sha256((sample_dir / name).read_bytes()).hexdigest()
        if actual != expected:
            raise ValueError(f"{name} 已变更，请重新从当前样板量取安装边和朝向")
    return validate_symbols(cache)


def validate_symbols(cache):
    for name, item in cache["symbols"].items():
        if "chordCenter" not in item:  # 箱体采用独立的原生背边。
            if name != "LEB":
                raise ValueError(f"{name} 缺少半圆弦中心")
            continue
        x, y = (b - a for a, b in zip(item["anchor"], item["chordCenter"]))
        angle = item["normalAngle"]
        if not math.isclose(math.hypot(x, y), item["width"] / 2, abs_tol=.1):
            raise ValueError(f"{name} 安装边至弦心距离异常")
        if abs(x * math.sin(angle) - y * math.cos(angle)) > .1 or x * math.cos(angle) + y * math.sin(angle) <= 0:
            raise ValueError(f"{name} 半圆弦不在朝房间的一侧")
    return cache["symbols"]


def check_pages(design, required_floors, camera_floors=(1,)):
    sheets = design["sheets"]
    by_number = {sheet["number"]: sheet for sheet in sheets}
    if len(by_number) != len(sheets):
        raise ValueError("图号重复")
    floors = Counter(s["floor"] for s in sheets if s["kind"] == "weak")
    missing = [f for f in required_floors if floors[f] != 1]
    if missing:
        raise ValueError(f"下列楼层缺少唯一的弱电平面图：{missing}")
    for d in design["devices"]:
        if d["kind"] not in {"TV", "TD", "ADD", "CAMERA"}:
            continue
        sheet = by_number.get(d["sheet"])
        if not sheet or sheet["floor"] != d["floor"] or sheet["kind"] != "weak":
            raise ValueError(f"{d['id']} 的弱电点位与图号或楼层不一致")
        if d["kind"] == "CAMERA" and d["floor"] not in camera_floors:
            raise ValueError(f"{d['id']} 超出本项目摄像头楼层范围")
    return sorted(floors)


def check_terminal_spans(devices, widths):
    """在出图前用实测图例宽度检查同楼层、同侧墙上的强弱电面板。"""
    issues = []
    for i, a in enumerate(devices):
        for b in devices[i+1:]:
            if a["floor"] != b["floor"] or not {a["kind"], b["kind"]} & {"TV", "TD"}:
                continue
            if a["kind"] not in widths or b["kind"] not in widths:
                continue
            normal = a["normal"]
            if math.cos(normal - b["normal"]) < .99999:
                continue
            dx, dy = (v - u for u, v in zip(a["p"][:2], b["p"][:2]))
            if abs(dx * math.cos(normal) + dy * math.sin(normal)) > .25:
                continue
            separation = abs(dy * math.cos(normal) - dx * math.sin(normal))
            if separation < (widths[a["kind"]] + widths[b["kind"]]) / 2 - .25:
                issues.append(f"{a['floor']}层强弱电面板安装边重叠：{a['id']}、{b['id']}")
    if issues:
        raise ValueError("\n".join(issues))


def socket_copy_parameters(symbol, world, normal):
    """用实测安装边及房间侧法向组装 copy 指令，保留样板实例自身的镜像。"""
    return dict(src=symbol["src"], handles=list(symbol["handles"]), anchor=symbol["anchor"],
                p=list(world[:2]), angle=normal - symbol["normalAngle"])


def check_copy_jobs(design, symbols):
    copies = defaultdict(list)
    for job in design["jobs"]:
        if job.get("op") == "copy":
            copies[job.get("tag")].append(job)
    issues = []
    count = 0
    seen = set()
    for tag, jobs in copies.items():
        if any(j.get("layer") == "EQUIP-插座" for j in jobs) and not tag:
            issues.append("插座复制指令缺少对应点位标识")
    for device in design["devices"]:
        symbol = symbols.get(device["kind"])
        if symbol is None:
            continue
        count += 1
        tag = f"dev-{device['sheet']}-{device['id']}"
        if tag in seen or len(copies[tag]) != 1:
            issues.append(f"{tag} 点位或对应的原生复制指令不唯一")
            continue
        seen.add(tag)
        job = copies[tag][0]
        if job.get("src") != symbol["src"] or job.get("handles") != symbol["handles"]:
            issues.append(f"{tag} 样板来源或图块不符")
            continue
        angle_error = job.get("angle", 0) + symbol["normalAngle"] - device["normal"]
        if not math.isclose(math.cos(angle_error), 1, abs_tol=1e-9):
            issues.append(f"{tag} 安装朝向不符")
        for field, expected in (("anchor", symbol["anchor"]), ("p", device["world"])):
            actual = job.get(field, [])[:2]
            if len(actual) != 2 or not math.dist(actual, expected[:2]) <= .1:
                issues.append(f"{tag} {'样板安装边基点' if field == 'anchor' else '图上安装点'}不符")
        if job.get("scale", 1) != 1:
            issues.append(f"{tag} 插块比例与实测安装宽度不符")
    for tag, jobs in copies.items():
        if tag and tag not in seen and any(j.get("layer") == "EQUIP-插座" for j in jobs):
            issues.append(f"{tag} 插座复制指令缺少对应点位或该类原生符号的校准")
    if issues:
        raise ValueError("\n".join(issues))
    return count


def inside_space(point, boundary):
    """Ray crossing on a room's accessible floor polygon, in floor-local coordinates."""
    x, y = point
    if len(boundary) < 3:
        raise ValueError("操作空间缺少实测边界")
    inside = False
    for (ax, ay), (bx, by) in zip(boundary, boundary[1:] + boundary[:1]):
        if (ay > y) != (by > y) and x < (bx - ax) * (y - ay) / (by - ay) + ax:
            inside = not inside
    return inside


def select_switch_site(floor, intent):
    """Select on surveyed clear spans only. Return the floor-local panel centre and facing."""
    rooms = floor["spaces"]
    route = intent["route"]
    role = intent["role"]
    access = floor["access"][intent["access"]]
    target = access["point"]
    if not route or len(set(route)) != len(route) or any(r not in rooms for r in route):
        raise ValueError("进出动线有歧义")
    if not all(rooms[r]["use"] for r in route):
        raise ValueError("沿途空间用途未识别")
    passages = [a["between"] for a in floor["access"].values() if "between" in a]
    for a, b in zip(route, route[1:]):
        if not any(set(pair) == {a, b} for pair in passages):
            raise ValueError("动线相邻空间缺少实际出入口")
    if role == "bedside":
        if access.get("kind") != "cabinet" or access["space"] != route[-1] or rooms[route[-1]]["use"] != "bedroom":
            raise ValueError("床头点未对应本卧室床头柜")
        operating = route[-1]
    else:
        if role not in {"entry", "shared"} or len(route) < 2:
            raise ValueError("门口点缺少进入前后的空间")
        if set(access.get("between", [])) != set(route[-2:]) or access.get("kind") not in {"door", "passage", "landing", "hatch"}:
            raise ValueError("候选门或敞开入口与进入动线不符")
        if [route[-2], intent["access"]] not in rooms[route[-1]]["entries"]:
            raise ValueError("该处不是从来向进入目标空间的日常操作入口")
        operating = route[-2] if rooms[route[-1]]["use"] == "bathroom" else route[-1]
        if role == "shared":
            operating = intent["operateIn"]
            if operating not in route[-2:] or not intent.get("reason"):
                raise ValueError("集中分控缺少邻近共用操作区或使用依据")
        if (rooms[route[-1]]["use"] == "bathroom" or role == "shared") and not rooms[operating]["dry"]:
            raise ValueError("卫生间或共用控制位置须在干区")
        if rooms[route[-1]]["use"] == "bathroom" and operating == route[-1]:
            raise ValueError("卫生间开关应在其入口外")

    width = intent["width"]
    if not math.isfinite(width) or width <= 0:
        raise ValueError("缺少面板实际宽度")
    candidates = []
    for face in floor["spans"]:
        if intent["access"] not in face["at"] or face["space"] != operating or not face["wall"]:
            continue
        start, end = face["ends"]
        length = math.dist(start, end)
        if length < width:
            continue
        tx, ty = ((b - a) / length for a, b in zip(start, end))
        offset = (target[0] - start[0]) * tx + (target[1] - start[1]) * ty
        offset = max(width / 2, min(length - width / 2, offset))
        p = [start[0] + tx * offset, start[1] + ty * offset]
        # Probe the operating side at the centre and ends of the actual panel footprint.
        sides = []
        for nx, ny in [(-ty, tx), (ty, -tx)]:
            probes = [[p[0]+tx*d+nx, p[1]+ty*d+ny] for d in (-width/2, 0, width/2)]
            boundary = access.get("approachBoundary", rooms[operating]["boundary"])
            # The local dry-side patch also has to land inside the identified operating room.
            if access.get("approachBoundary") and not inside_space([p[0]+70*nx,p[1]+70*ny], rooms[operating]["boundary"]):
                continue
            if access.get("swing") and not access.get("fallbackObstacle"):
                from entry_and_leader import latch_side
                if not all(latch_side(q, access["swing"]) for q in probes):
                    continue
            if all(inside_space(q, boundary) for q in probes):
                sides.append(math.atan2(ny, nx))
        if len(sides) == 1:
            candidates.append((face.get("priority", 0), math.dist(p, target), face["wall"], p, sides[0]))
    if not candidates:
        raise ValueError("该入口操作侧无可达且足宽的实墙，点位待定")
    _, _, wall, p, normal = min(candidates)
    return dict(p=p, normal=normal, wall=wall, space=operating)


def check_switch_sites(design):
    devices = design["devices"]
    copy_jobs = defaultdict(list)
    for job in design.get("jobs", []):
        if job.get("op") == "copy":
            copy_jobs[job.get("tag")].append(job)
    control_targets = defaultdict(set)
    for edge in design.get("edges", []):
        if edge.get("role") == "control":
            control_targets[edge["fromId"]].add(edge["toId"])
    contexts = design.get("switchSpaces", {})
    issues = []
    switch_tags = set()
    for point in design.get("pendingSwitches", []):
        issues.append(f"{point['id']}：开关待定位，{point['reason']}")
    for d in devices:
        tag = f"dev-{d['sheet']}-{d['id']}"
        copies = copy_jobs[tag]
        if not (d["kind"] in {"SW", "SW2", "SW3", "DUAL"} or d["id"] in control_targets
                or any(j.get("layer") == "EQUIP-开关" for j in copies)):
            continue
        switch_tags.add(tag)
        try:
            intent = d.get("switchIntent")
            if not intent or str(d["floor"]) not in contexts:
                raise ValueError("缺少绘图前的空间、动线与安装面依据")
            floor = contexts[str(d["floor"])]
            site = select_switch_site(floor, intent)
            targets = intent["lights"]
            if not targets or set(targets) != control_targets[d["id"]]:
                raise ValueError("操作意图与实际受控灯具不符")
            if any(floor["lampSpaces"][lamp] != intent["route"][-1] for lamp in targets) and intent["role"] != "shared":
                raise ValueError("受控灯所在空间与操作用途不符")
            if intent["role"] == "shared":
                for lamp in targets:
                    room = floor["lampSpaces"][lamp]
                    if floor["spaces"][room]["use"] == "bedroom":
                        entrances = floor["spaces"][room]["entries"]
                        if site["space"] != room or not any(door == intent["access"] for _, door in entrances):
                            raise ValueError("集中面板的卧室主灯键须从卧室入口直接操作")
                    if room != site["space"] and not any(
                        a.get("between") and set(a["between"]) == {site["space"], room}
                        for a in floor["access"].values()
                    ):
                        raise ValueError("集中控制灯组与操作区缺少直接通行关系")
            if not (math.dist(d["p"][:2], site["p"]) <= .25 and math.cos(d["normal"] - site["normal"]) > .99999):
                raise ValueError("实际点位或朝向偏离该入口合格墙面")
            world = [x + offset for x, offset in zip(site["p"], floor["sheetOrigins"][d["sheet"]])]
            if len(copies) != 1 or not math.dist(copies[0]["p"][:2], world) <= .25:
                raise ValueError("实际开关插块指令与选点结果不一致")
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            issues.append(f"{d['sheet']} {d['id']} {d.get('room','')}：{exc}")
    for tag, jobs in copy_jobs.items():
        if tag not in switch_tags and any(j.get("layer") == "EQUIP-开关" and
                                         (not tag or str(tag).startswith("dev-")) for j in jobs):
            issues.append(f"{tag or '未编号'}：开关插块缺少对应操作点")
    if issues:
        raise ValueError("\n".join(issues))


def on_segment(p, ends):
    a, b = ends
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = math.hypot(dx, dy)
    if length == 0:
        return False
    t = ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / length**2
    return 0 <= t <= 1 and math.dist(p[:2], [a[0] + t * dx, a[1] + t * dy]) <= 0.5


def outdoor_mount_kind(point, survey):
    """Use surveyed support at the actual anchor, in floor-local millimetres."""
    for face in survey.get("walls", []):
        if face.get("source") and on_segment(point, face["ends"]):
            return "wall"
    for slab in survey.get("slabs", []):
        if not slab.get("source"):
            continue
        outlines = [slab["boundary"], *slab.get("holes", [])]
        if any(on_segment(point, (a, b)) for ring in outlines
               for a, b in zip(ring, ring[1:] + ring[:1])):
            continue
        if inside_space(point, outlines[0]) and not any(inside_space(point, hole) for hole in outlines[1:]):
            return "ceiling"
    return None


def check_light_coverage(design):
    """Check expected usable zones surveyed from the base plan against actual fixture centres."""
    lamps = defaultdict(list)
    for d in design["devices"]:
        if d["kind"] in {"LIGHT", "WETLIGHT", "WALLLIGHT"}:
            lamps[d["sheet"]].append(d)
    issues = []
    for sheet in design["sheets"]:
        if sheet["kind"] != "lighting":
            continue
        number = sheet["number"]
        zones = design.get("lightingZones", {}).get(number)
        if not zones:
            issues.append(f"{number} 缺少由建筑底图独立识别的应照明区域")
            continue
        counted = set()
        for zone in zones:
            boundary = zone["boundary"]
            outdoor = "outdoorMount" in zone or any(s in zone["name"] for s in ("露台", "阳台", "露天"))
            if outdoor:
                inside = set()
                survey = zone.get("outdoorMount") or {}
                for d in lamps[number]:
                    point = d["p"][:2]
                    within = inside_space(point, boundary)
                    edge = any(on_segment(point, (a, b)) for a, b in zip(boundary, boundary[1:] + boundary[:1]))
                    if not (within or edge):
                        continue
                    support = outdoor_mount_kind(point, survey)
                    expected = "wall" if d["kind"] == "WALLLIGHT" else "ceiling"
                    if support != expected:
                        missing = "实际外墙或固定柱安装面" if expected == "wall" else "灯位正上方可安装板底"
                        issues.append(f"{number} {zone['name']} {d['id']} 缺少{missing}依据")
                    elif "kinds" in zone and d["kind"] not in zone["kinds"]:
                        issues.append(f"{number} {zone['name']} {d['id']} 与选定的灯具图例不符")
                    else:
                        inside.add(d["id"])
            else:
                kinds = zone.get("kinds", ["LIGHT", "WETLIGHT"])
                inside = {d["id"] for d in lamps[number] if d["kind"] in kinds and
                          inside_space(d["p"][:2], boundary)}
            minimum = zone["minimum"]
            if type(minimum) is not int or minimum < 1 or len(inside) < minimum:
                issues.append(f"{number} {zone['name']} 应布 {minimum} 盏，实有 {len(inside)} 盏")
            if counted & inside:
                issues.append(f"{number} {zone['name']} 与其他区域重复计灯，请核对边界")
            counted.update(inside)
    if issues:
        raise ValueError("\n".join(issues))


def package_preflight(design_path, cache_path, required_floors, camera_floors, widths):
    design = read(design_path)
    if "priorHash" in design or "edits" in design:
        raise ValueError("此入口核对全新组装指令。基于保存 DWG 的差量修订请使用修订流程。")
    cache = read(cache_path)
    issues = []
    symbols = None
    try:
        # Check the files that the build will actually load (sources can be renamed).
        for src in {entry["src"] for entry in cache["symbols"].values()}:
            name = src + ".dwg"
            actual = design_path.parent / design["sources"][src]
            if sha256(actual.read_bytes()).hexdigest() != cache["sampleSHA256"].get(name):
                raise ValueError(f"{src} 样板与校准记录不一致，请用当前原生样板重新量取")
        symbols = validate_symbols(cache)
    except (KeyError, OSError, ValueError) as exc:
        issues.append(str(exc))
    try:
        check_pages(design, required_floors, camera_floors)
    except ValueError as exc:
        issues.append(str(exc))
    try:
        check_switch_sites(design)
    except ValueError as exc:
        issues.append(str(exc))
    try:
        check_light_coverage(design)
    except ValueError as exc:
        issues.append(str(exc))
    issues.extend(check_architectural_lighting(design_path, design))
    count = 0
    if symbols is not None:
        try:
            count = check_copy_jobs(design, symbols)
        except ValueError as exc:
            issues.append(str(exc))
    needed = {d["kind"] for d in design["devices"] if d["kind"] in {"TV", "TD"}}
    active_widths = dict(widths)
    if symbols:
        active_widths.update({k: s["width"] for k, s in symbols.items()})
    if any(not math.isfinite(w) or w <= 0 for w in active_widths.values()) or needed - active_widths.keys():
        issues.append("缺少或无效的实际安装边宽度，请核对 TV/TD 等点位的样板实测数据")
    else:
        try:
            check_terminal_spans(design["devices"], active_widths)
        except ValueError as exc:
            issues.append(str(exc))
    if issues:
        raise ValueError("\n".join(issues))
    return count


def check_architectural_lighting(path, design):
    from lighting_survey import lamp_copy_errors, read_basis, survey_errors
    if not any(s["kind"] == "lighting" for s in design["sheets"]):
        return []
    try:
        # Enforce current evidence on submission. Preserve historical readback on archived projects.
        contexts = {f: dict(context, requireDoorEvidence=True) for f, context in design["switchSpaces"].items()}
        current = dict(design, switchSpaces=contexts)
        return survey_errors(current, read_basis(path, design), design["devices"]) + lamp_copy_errors(design)
    except (ValueError, KeyError, TypeError, OSError) as exc:
        return [str(exc)]


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    commands = cli.add_subparsers(dest="command", required=True)
    sockets = commands.add_parser("sockets")
    sockets.add_argument("sample_dir", type=Path)
    sockets.add_argument("output", type=Path)
    sockets.add_argument("--cache", type=Path, default=Path(__file__).with_name("socket-template-cache.json"))
    package = commands.add_parser("package", help="新项目入池前核对实际 build.json 及其样板")
    package.add_argument("design", type=Path)
    package.add_argument("--cache", type=Path, default=Path(__file__).with_name("socket-template-cache.json"))
    package.add_argument("--weak-floors", nargs="*", required=True, type=int)
    package.add_argument("--camera-floors", nargs="*", type=int, default=[1])
    package.add_argument("--mount-widths", required=True, type=Path)
    pages = commands.add_parser("sheets")
    pages.add_argument("design", type=Path)
    pages.add_argument("--weak-floors", nargs="+", required=True, type=int)
    pages.add_argument("--camera-floors", nargs="+", type=int, default=[1])
    pages.add_argument("--mount-widths", type=Path, help="样板量取的设备种类与安装边宽度，模型毫米")
    args = cli.parse_args()
    if args.command == "package":
        try:
            count = package_preflight(args.design, args.cache, args.weak_floors, args.camera_floors, read(args.mount_widths))
        except (KeyError, OSError, TypeError, ValueError) as exc:
            cli.exit(1, f"{exc}\n")
        print(f"入池前核对通过，{count} 个已校准设备的实际插块指令")
    elif args.command == "sockets":
        symbols = socket_calibration(args.sample_dir, read(args.cache))
        args.output.write_text(json.dumps(symbols, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"已核对样板，复用 {len(symbols)} 类原生块参数")
    else:
        design = read(args.design)
        print("弱电图楼层", check_pages(design, args.weak_floors, args.camera_floors))
        if args.mount_widths:
            check_terminal_spans(design["devices"], read(args.mount_widths))
        issues = check_architectural_lighting(args.design, design)
        if issues:
            cli.exit(1, "\n".join(issues) + "\n")


if __name__ == "__main__":
    main()
