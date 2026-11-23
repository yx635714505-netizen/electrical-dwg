"""核对保存后各层底图块及其嵌套块中的清理结果。"""
from collections import Counter
import argparse
import json
from pathlib import Path


def verify(native, plan):
    blocks = native["blocks"]
    errors = []
    def visit(name, ancestors):
        if name in ancestors:
            raise ValueError(f"底图块循环引用 {name}")
        for entity in blocks[name]:
            yield entity
            if entity["type"] == "INSERT":
                yield from visit(entity["block"], ancestors | {name})

    if not plan:
        raise ValueError("底图清单为空")
    for item in plan:
        entities = list(visit(item["base"], set()))
        by_handle = {e["h"]: e for e in entities}
        for h in item["remove"]:
            if h in by_handle:
                errors.append(f"{item['base']} 仍有应清理的图元 {h}")
        for h, kind in item["retain"].items():
            if by_handle.get(h, {}).get("type") != kind:
                errors.append(f"{item['base']} 缺少应保留的 {kind} {h}")
        for e in entities:
            if (e["type"] == "LWPOLYLINE" and e["layer"].split("$")[-1].casefold() == "defpoints"
                    and e.get("closed") and len(e.get("vertices", [])) == 4
                    and e["h"] not in item["retain"]):
                errors.append(f"{item['base']} 存在未分类的四边辅助框候选 {e['h']}")
        counts = Counter(e["type"] for e in entities)
        if counts["TCH_DIMENSION2"] != item["nativeDimensionCount"]:
            errors.append(f"{item['base']} 剩余天正尺寸数量与本层确认清单不符")
    return errors


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("native", type=Path)
    ap.add_argument("plan", type=Path)
    args = ap.parse_args()
    load = lambda p: json.loads(p.read_text(encoding="utf-8-sig"))
    issues = verify(load(args.native), load(args.plan))
    for issue in issues:
        print(issue)
    raise SystemExit(bool(issues))
