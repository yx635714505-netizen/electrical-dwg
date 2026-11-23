"""核对已保存 DWG 中图签值的唯一性、入格和文字重叠。"""
import math
import unicodedata


def normalized(text):
    return "".join(unicodedata.normalize("NFKC", text).split())


def overlaps(a, b):
    return min(a[2], b[2]) > max(a[0], b[0]) and min(a[3], b[3]) > max(a[1], b[1])


def contains(outer, inner):
    return (outer[0] <= inner[0] and outer[1] <= inner[1]
            and outer[2] >= inner[2] and outer[3] >= inner[3])


def title_texts(native, sheet, area):
    blocks = native["blocks"]
    hidden = {row["name"].casefold() for row in native.get("layers", [])
              if row.get("off") or row.get("frozen") or row.get("plot") is False}

    def visit(items, project, path, layer):
        for e in items:
            active = e.get("layer", "0")
            if active == "0":
                active = layer
            if active.casefold() in hidden or e.get("invisible") or e.get("visible") is False:
                continue
            kind = e["type"]
            if kind not in ("INSERT", "TEXT", "MTEXT", "ATTRIB", "TCH_TEXT", "TCH_MTEXT", "ATTDEF"):
                continue
            if kind == "ATTDEF" and not e.get("constant"):
                continue
            if "bbox" not in e:
                if kind == "INSERT":
                    raise ValueError(f"块 {e['h']} 缺少几何范围")
                continue
            lo, hi = e["bbox"]
            corners = [project(x, y) for x in (lo[0], hi[0]) for y in (lo[1], hi[1])]
            xs, ys = zip(*corners)
            box = min(xs), min(ys), max(xs), max(ys)
            if not overlaps(box, area):
                continue
            if kind != "INSERT":
                text = e.get("text") or "".join(e.get("nativeText", []))
                if text.strip():
                    yield normalized(text), box, e["h"]
                continue
            name = e["block"]
            if name in path or name not in blocks:
                raise ValueError(f"图签内的块 {name} 无法展开")
            # ATTRIB 的回读坐标已经位于所属 INSERT 的父坐标系。
            yield from visit(e.get("attrs", []), project, path, active)
            ox, oy = e["pos"][:2]
            sx, sy = e.get("scale", [1, 1])[:2]
            angle = e.get("angle", 0)
            c, s = math.cos(angle), math.sin(angle)
            bx, by = native.get("blockOrigins", {}).get(name, [0, 0])[:2]

            def placed(x, y):
                u, v = (x-bx)*sx, (y-by)*sy
                return project(ox + c*u - s*v, oy + s*u + c*v)

            yield from visit(blocks[name], placed, path + (name,), active)

    return list(visit(blocks["*Model_Space"],
                      lambda x, y: (x-sheet["x"], y-sheet["y"]), (), "0"))


def field_errors(native, sheet, spec):
    errors = []
    area = spec["area"]
    texts = title_texts(native, sheet, area)
    fields = [("number", "图号", normalized(sheet["number"])),
              ("scale", "比例", normalized(spec.get("scaleValue", "1:100"))),
              ("date", "日期", normalized(spec["dateValue"]))]
    for key, label, expected in fields:
        cell = spec.get(key)
        if not cell or not contains(area, cell):
            errors.append(f"缺少有效的{label}值格")
        matches = [i for i, (value, box, _) in enumerate(texts) if value == expected
                   and (key != "date" or not cell or overlaps(box, cell))]
        if len(matches) != 1:
            errors.append(f"{label}应有一个 {expected}，实有 {len(matches)} 个")
        if cell:
            intruders = [v for v, box, _ in texts if overlaps(cell, box) and v != expected]
            if intruders:
                errors.append(f"{label}值格混入文字 " + "、".join(intruders))
        for i in matches:
            _, box, h = texts[i]
            if cell and not contains(cell, box):
                errors.append(f"{label} {h} 超出值格")
            for j, (other, otherbox, _) in enumerate(texts):
                if i != j and overlaps(box, otherbox):
                    errors.append(f"{label} {h} 与 {other} 重叠")
    return errors


def verify(native, sheets, specs):
    errors = []
    for sheet in sheets:
        number = sheet["number"]
        try:
            problems = field_errors(native, sheet, specs[number])
        except (KeyError, ValueError, TypeError) as exc:
            problems = [f"图签依据或原生回读不完整 {exc}"]
        errors.extend(f"{number} {problem}" for problem in problems)
    return errors
