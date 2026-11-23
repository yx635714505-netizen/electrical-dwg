"""Compare lighting switches with the original equipment legend in a saved DWG survey."""
import argparse
import json
from pathlib import Path

from validate_presentation import contained


def validate(details, sheets, schedule):
    model = {e["h"]: e for e in details["blocks"]["*Model_Space"]}
    errors = []
    frame_id = schedule["legendFrame"]
    note_frames = {s["frameHandle"] for s in sheets if s["kind"] == "notes"}
    if frame_id not in note_frames:
        return ["设备图例表须位于电气设计说明图框内"]
    frame = model[frame_id]["bbox"]
    if any(s["kind"] == "lighting" for s in sheets) and not schedule["instances"]:
        errors.append("照明页缺少按控制设计逐项编制的开关清单")
    rows = {}
    for name, row in schedule["rows"].items():
        symbol = model.get(row["symbol"], {})
        caption = model.get(row["caption"], {})
        words = caption.get("text") or "".join(caption.get("nativeText", []))
        symbol_box = symbol.get("bbox")
        text_box = caption.get("bbox")
        if (symbol.get("type") != "INSERT" or not details["blocks"].get(symbol.get("block"))
                or words.strip() != name or not contained(symbol_box, frame)
                or not contained(text_box, frame)):
            errors.append(f"设备图例表原行不符：{name}")
            continue
        if min(symbol_box[1][1], text_box[1][1]) < max(symbol_box[0][1], text_box[0][1]):
            errors.append(f"图例块与名称未在同一行：{name}")
            continue
        rows[name] = symbol["block"]

    frames = [model[s["frameHandle"]]["bbox"] for s in sheets if s["kind"] == "lighting"]
    layers = {"EQUIP-开关", *schedule.get("switchLayers", [])}
    instances = schedule["instances"]
    seen = set()
    for h, entity in model.items():
        if not any(contained(entity.get("bbox"), bounds) for bounds in frames):
            continue
        block = entity.get("block")
        switch_attribute = any("开关" in a.get("text", "") for a in entity.get("attrs", []))
        if not (h in instances or entity["layer"] in layers or block in rows.values() or switch_attribute):
            continue
        seen.add(h)
        if h not in instances:
            errors.append(f"{h} 照明页开关或随图图例遗漏于清单")
        elif entity.get("type") != "INSERT" or instances[h] not in rows or block != rows[instances[h]]:
            errors.append(f"{h} 应直接复用设备图例表「{instances[h]}」的原生块定义")
    for h in sorted(instances.keys() - seen):
        errors.append(f"{h} 清单实例未在照明平面原生回读中找到")
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("details", "sheets", "schedule"):
        parser.add_argument(name, type=Path)
    args = parser.parse_args()
    inputs = [json.loads(p.read_text(encoding="utf-8-sig"))
              for p in (args.details, args.sheets, args.schedule)]
    findings = validate(*inputs)
    print(json.dumps({"passed": not findings, "errors": findings}, ensure_ascii=False, indent=2))
    return bool(findings)


if __name__ == "__main__":
    raise SystemExit(main())

