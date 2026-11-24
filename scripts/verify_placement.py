"""Independent support checks using actual native-readback mounting geometry."""
from __future__ import annotations
import argparse
from collections import Counter
import json
import math
from pathlib import Path
from placement_geometry import (IDENTITY, point, unit, sub, dot, cross, frame,
    compose, block_transform, transform_point, check_edge, polygons_overlap)


def flatten(details, entity, matrix=IDENTITY, chain=()):
    name=entity.get("block")
    if entity.get("type")=="INSERT":
        if not name or name in chain or len(chain)>24:
            raise ValueError("Missing/cyclic/deep native block "+str(name))
        if name not in details.get("blocks",{}):
            raise ValueError("Missing native block "+name)
        matrix=compose(matrix,block_transform(entity))
        for child in details["blocks"][name]:
            yield from flatten(details,child,matrix,chain+(name,))
    else:
        yield entity,matrix,chain


def socket_mount(details, entity):
    """Semicircle chord and inward symbol direction from native ARC endpoints."""
    arcs=[]
    try:
        for e,m,chain in flatten(details,entity):
            if e.get("type")!="ARC":
                continue
            if not all(k in e for k in ("start","end","mid","sweep")):
                return {"status":"pending","reason":"Native ARC endpoints/sweep not exported"}
            if abs(abs(e["sweep"])-math.pi)>1e-5:
                continue
            a,b,mid=(transform_point(m,e[k]) for k in ("start","end","mid"))
            center=((a[0]+b[0])/2,(a[1]+b[1])/2)
            # Under nonuniform scaling, the diameter direction still determines
            # the installation tangent; remove tangential skew from midpoint.
            tangent=unit(sub(b,a));side=sub(mid,center)
            normal=(-tangent[1],tangent[0])
            if dot(normal,side)<0:normal=(-normal[0],-normal[1])
            raw0,raw1,rawmid=(point(e[k]) for k in ("start","end","mid"))
            rt=unit(sub(raw1,raw0));rn=(-rt[1],rt[0]);rc=((raw0[0]+raw1[0])/2,(raw0[1]+raw1[1])/2)
            height=dot(sub(rawmid,rc),rn)
            footprint=[transform_point(m,p) for p in (raw0,raw1,(raw1[0]+rn[0]*height,raw1[1]+rn[1]*height),(raw0[0]+rn[0]*height,raw0[1]+rn[1]*height))]
            arcs.append({"edge":[a,b],"normal":normal,"footprint":footprint,"arc":e["h"],"chain":list(chain)})
    except (ValueError,KeyError,TypeError) as ex:
        return {"status":"pending","reason":str(ex)}
    if len(arcs)!=1:
        return {"status":"pending","reason":"Expected one identifiable native semicircle; found "+str(len(arcs))}
    return dict(status="passed",**arcs[0])


def socket_mount_from_chord(details,entity,tolerance):
    """Explicit reviewed profile for older exports: actual chord LINE + half ARC.
    Only axis-aligned local semicircle extents with an actual matching diameter
    line are supported; never infer the chord just from an insertion point.
    """
    found=[]
    try:
        parts=list(flatten(details,entity))
        for arc,m,chain in parts:
            if arc.get("type")!="ARC" or not arc.get("bbox"):
                continue
            box=arc["bbox"]
            lo,hi=map(point,box);dx,dy=hi[0]-lo[0],hi[1]-lo[1]
            if min(dx,dy)<=tolerance:continue
            axis=0 if dx>dy else 1;other=1-axis
            if abs(max(dx,dy)-2*min(dx,dy))>tolerance:continue
            for line,lm,lc in parts:
                if line.get("type")!="LINE" or lc!=chain or lm!=m or len(line.get("vertices",[]))!=2:continue
                a,b=map(point,line["vertices"])
                if abs(a[other]-b[other])>tolerance:continue
                if abs(min(a[axis],b[axis])-lo[axis])>tolerance or abs(max(a[axis],b[axis])-hi[axis])>tolerance:continue
                boundary=(a[other]+b[other])/2
                if min(abs(boundary-lo[other]),abs(boundary-hi[other]))>tolerance:continue
                side=[(lo[0]+hi[0])/2,(lo[1]+hi[1])/2]
                center=[(a[0]+b[0])/2,(a[1]+b[1])/2]
                a1,b1=transform_point(m,a),transform_point(m,b)
                tangent=unit(sub(b1,a1));normal=(-tangent[1],tangent[0])
                direction=sub(transform_point(m,side),transform_point(m,center))
                if dot(normal,direction)<0:normal=(-normal[0],-normal[1])
                footprint=[transform_point(m,p) for p in ((lo[0],lo[1]),(hi[0],lo[1]),(hi[0],hi[1]),(lo[0],hi[1]))]
                found.append({"edge":[a1,b1],"normal":normal,"footprint":footprint,"arc":arc["h"],"chord":line["h"],"chain":list(chain)})
    except (ValueError,KeyError,TypeError) as ex:
        return {"status":"pending","reason":str(ex)}
    if len(found)!=1:return {"status":"pending","reason":"Reviewed chord profile ambiguous/missing: "+str(len(found))}
    return dict(status="passed",**found[0])

def _status(rows):
    values=[r["status"] for r in rows]
    return "failed" if "failed" in values else "pending" if "pending" in values or not rows else "passed"


def _edge_overlap(a,b,tol):
    p,u,length=frame(*a)
    if max(abs(cross(sub(point(v),p),u)) for v in b)>tol:
        return False
    lo,hi=sorted(dot(sub(point(v),p),u) for v in b)
    return min(length,hi)-max(0,lo)>tol


def validate_geometry(source, instances, tolerance, *, support_only=False):
    if not math.isfinite(tolerance) or tolerance<=0:
        raise ValueError("Tolerance must be a positive finite project value")
    points=[]
    counts=Counter(v.get("id") for v in instances)
    for v in instances:
        row={"id":v.get("id"),"handles":v.get("handles",[]),
             "sheet":v.get("sheet"),"floor":v.get("floor"),
             "status":"pending","reasons":[],"evidence":{}}
        points.append(row)
        if not v.get("id") or counts[v.get("id")]!=1:
            row.update(status="failed",reasons=["duplicate_or_missing_id"]);continue
        if not v.get("handles") or v.get("floor") is None or not v.get("sheet"):
            row["reasons"]=["missing_native_identity"];continue
        if not v.get("mountingEdge") or not v.get("normal"):
            row["reasons"]=["unsupported_or_unexported_mounting_geometry"];continue
        faces=[f for f in source.get("faces",[]) if f["floor"]==v["floor"]]
        openings=[o for o in source.get("openings",[]) if o["floor"]==v["floor"]]
        obstacles=[o for o in source.get("obstacles",[]) if o["floor"]==v["floor"]]
        if not faces:
            row["reasons"]=["source_floor_geometry_missing"];continue
        checked=[]
        try:
            for face in faces:
                blockers=[o for o in obstacles if o["id"]!=face.get("source_handle")]
                checked.append(check_edge(v["mountingEdge"],v["normal"],face,openings,blockers,tolerance))
        except (ValueError,KeyError,TypeError) as ex:
            row["reasons"]=["invalid_source_or_mounting_geometry: "+str(ex)];continue
        good=[r for r in checked if r["status"]=="passed"]
        if not good:
            # Nearest collinear faces provide useful aperture/short-wall failure
            # evidence even when they cannot support the symbol.
            near=[r for r in checked if "not_on_face" not in r["reasons"] and "wrong_side" not in r["reasons"]]
            row.update(status="failed",reasons=sorted({x for r in near for x in r["reasons"]}) or ["no_actual_support_face"])
            row["evidence"]={"candidates":near};continue
        row.update(status="passed",evidence={"support":good})
        if not support_only and not v.get("footprint"):
            row.update(status="pending",reasons=["native_body_footprint_missing"])
        pending=[x for x in source.get("pending",[]) if x.get("floor") in (None,v["floor"])]
        if pending:
            row.update(status="pending",reasons=["source_geometry_incomplete"])
            row["evidence"]["unsupported"]=pending
        if v.get("footprint"):
            try:
                collision=[o["id"] for o in obstacles if polygons_overlap(v["footprint"],o["polygon"],tolerance)]
                if collision:row.update(status="failed",reasons=["footprint_inside_obstacle"])
                row["evidence"]["footprintObstacles"]=collision
            except ValueError as ex:
                row.update(status="pending",reasons=[str(ex)])
    collisions=[]
    by_id={r["id"]:r for r in points}
    for i,a in enumerate(instances):
        for b in instances[i+1:]:
            if a.get("floor")!=b.get("floor") or not a.get("mountingEdge") or not b.get("mountingEdge"):
                continue
            if a.get("physical_id") and a.get("physical_id")==b.get("physical_id") and a.get("sheet")!=b.get("sheet"):
                ea,eb=a["mountingEdge"],b["mountingEdge"]
                same=min(max(math.dist(ea[i],eb[i]) for i in range(2)),
                         max(math.dist(ea[i],eb[1-i]) for i in range(2)))<=tolerance
                if not same:
                    for v in (a,b):
                        by_id[v["id"]]["status"]="failed"
                        by_id[v["id"]]["reasons"].append("inconsistent_cross_sheet_representation")
                continue
            try:
                if dot(unit(a["normal"]),unit(b["normal"]))<1-1e-6:continue
                if _edge_overlap(a["mountingEdge"],b["mountingEdge"],tolerance):
                    collisions.append([a["id"],b["id"]])
                    for v in (a,b):
                        by_id[v["id"]]["status"]="failed"
                        by_id[v["id"]]["reasons"].append("plan_symbol_edges_overlap")
            except (ValueError,KeyError):
                continue  # The affected point already has a pending/error result.
    status=_status(points)
    return {"status":status,"passed":status=="passed","count":len(points),"acceptanceEligible":not support_only,
            "counts":dict(Counter(r["status"] for r in points)),
            "points":points,"collisions":collisions,
            "evidence":{"method":"complete native mounting-edge vs source faces and apertures", "tolerance":tolerance},
            "scope":"Actual complete mounting-edge support, opening/obstacle subtraction, direction and cross-sheet edge conflicts. Room/door-operation semantics, electrical control and visual checks are separate required reports."}


def verify_bundle(source_path, actual_path, manifest_path, tolerance):
    from validate_delivery import bound_inputs
    try:
        bindings,paths=bound_inputs(manifest_path)
        if Path(source_path).resolve()!=paths["geometry_source"] or Path(actual_path).resolve()!=paths["actual"]:
            raise ValueError("Geometry input does not match manifest")
        source=json.loads(Path(source_path).read_text("utf-8-sig"))
        actual=json.loads(Path(actual_path).read_text("utf-8-sig"))
        report=validate_geometry(source,actual["instances"],tolerance)
        report["drawing_sha256"]=bindings["drawing"]
        report["inputs"]=bindings
        return report
    except (OSError,ValueError,KeyError,TypeError) as ex:
        return {"status":"failed","passed":False,"errors":[str(ex)],"acceptanceEligible":False}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source",type=Path,required=True)
    parser.add_argument("--actual",type=Path,required=True)
    parser.add_argument("--manifest",type=Path,required=True)
    parser.add_argument("--tolerance",type=float,required=True)
    parser.add_argument("--report",type=Path,required=True)
    args=parser.parse_args()
    report=verify_bundle(args.source,args.actual,args.manifest,args.tolerance)
    args.report.write_text(json.dumps(report,ensure_ascii=False,indent=2),"utf8")
    print(json.dumps({k:v for k,v in report.items() if k!="points"},ensure_ascii=False))
    return 0 if report["passed"] else 1


if __name__=="__main__":raise SystemExit(main())
