"""Check the actual text, wall anchor and shelf knee of approved native transfer notes."""
import argparse
import json
import math
import re
from pathlib import Path


def check(plan, dump, *, all_leaders=False):
    entities = {}
    for line in dump.splitlines():
        if '(0 . "TCH_MULTILEADER")' in line:
            handle = re.search(r'\(5 \. "([^"]+)"\)', line).group(1)
            entities[handle] = line
    errors = []
    if not plan or len({row["h"] for row in plan}) != len(plan):
        errors.append("转接引注清单为空或句柄重复")
    if all_leaders:
        for handle in sorted(entities.keys() - {row["h"] for row in plan}):
            errors.append(f"{handle} 已回读但未纳入引注清单")
    for row in plan:
        h = row["h"]
        line = entities.get(h, "")
        if not line:
            errors.append(f"{h} 缺天正原生引注")
            continue
        field = re.search(r'\(1 \. "([^"]*)"\)', line)
        if not field or field.group(1) != row["text"]:
            errors.append(f"{h} 引注文字变化")
        for code, key in ((10, "tip"), (11, "knee")):
            match = re.search(rf'\({code} ([^)]*)\)', line)
            point = list(map(float, match.group(1).split()[:2])) if match else None
            if not point or math.dist(point, row[key]) > 0.6:
                errors.append(f"{h} {key} 与选定位置不符")
        # In a horizontal TCH_MULTILEADER the signed group 42 gives shelf direction.
        shelf = re.search(r'\(42 \. ([^)]*)\)', line)
        dx = row["knee"][0] - row["tip"][0]
        if not shelf or dx * float(shelf.group(1)) <= 0:
            errors.append(f"{h} 斜引线与水平横线折返或横向长度为零")
    return errors


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan", type=Path)
    parser.add_argument("dump", type=Path)
    parser.add_argument("--encoding", default="gbk")
    parser.add_argument("--all-leaders", action="store_true", help="核对回读范围内所有原生引注均已列入清单")
    args = parser.parse_args()
    rows = json.loads(args.plan.read_text("utf-8-sig"))
    issues = check(rows, args.dump.read_text(args.encoding), all_leaders=args.all_leaders)
    print("\n".join(issues) if issues else f"{len(rows)} 处原生引注的文字、锚点、折点与同向横线均通过")
    raise SystemExit(bool(issues))
