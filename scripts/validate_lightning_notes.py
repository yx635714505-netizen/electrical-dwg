"""Check native Tianzheng lightning-note text against the user's V34 reference."""
from __future__ import annotations
import argparse
import json
import re
from pathlib import Path


def normalize(text: str) -> str:
    return re.sub(r"\s+", "", re.sub(r"%%[cC]", "φ", text))


def validate(probe: dict, handles: list[str], expected: str) -> dict:
    entities = {
        str(e.get("h", "")).upper(): e
        for entries in probe.get("blocks", {}).values()
        for e in entries
    }
    results = []
    for handle in handles:
        handle = handle.upper()
        entity = entities.get(handle)
        errors = []
        if entity is None:
            errors.append("Handle missing from independent native readback")
        elif entity.get("type") != "TCH_MTEXT":
            errors.append("Expected native TCH_MTEXT")
        else:
            parts = entity.get("nativeText")
            if not isinstance(parts, list) or not parts or not all(isinstance(p, str) for p in parts):
                errors.append("Native text content missing from readback")
            elif normalize("".join(parts)) != normalize(expected):
                errors.append("Full note content differs from the V34 reference")
        results.append({"handle": handle, "passed": not errors, "errors": errors})
    return {
        "passed": bool(results) and all(r["passed"] for r in results),
        "checkedCount": len(results),
        "scope": "Selected notes' native type and full wording; geometry and engineering conditions require separate checks",
        "results": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--probe", type=Path, required=True)
    parser.add_argument("--notes-handle", action="append", required=True,
                        help="Repeat for every required note block in the project sheet list")
    parser.add_argument("--canonical", type=Path,
                        default=Path(__file__).resolve().parents[1] / "assets/lightning-grounding-notes-v34.txt")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    expected = args.canonical.read_text(encoding="utf-8-sig")
    probe = json.loads(args.probe.read_text(encoding="utf-8-sig"))
    report = validate(probe, args.notes_handle, expected)
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
