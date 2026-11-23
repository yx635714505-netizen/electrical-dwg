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


if __name__ == "__main__":
    main()

