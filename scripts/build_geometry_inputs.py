"""Adapt native exports to reusable geometry; unsupported shapes remain explicit."""
from __future__ import annotations
import argparse
import json
import math
import hashlib
from pathlib import Path
from placement_geometry import (IDENTITY, point, sub, dot, frame, unit, polygon,
    opening_polygon, transform_point, compose, cross)
from verify_placement import socket_mount, socket_mount_from_chord, flatten


def in_region(bbox,region):
    if not bbox:return False
    return (bbox[1][0]>=region[0][0] and bbox[0][0]<=region[1][0]
            and bbox[1][1]>=region[0][1] and bbox[0][1]<=region[1][1])


def _native_rectangle(e,tol):
    grips=e.get("grips",[])
    if len(grips)<3:raise ValueError("No native straight-wall centerline")
    a,u,length=frame(grips[0],grips[1]);b=point(grips[1])
    mid=((a[0]+b[0])/2,(a[1]+b[1])/2)
    if math.dist(mid,point(grips[2]))>tol:
        raise ValueError("Native wall is not a proven straight segment")
    box=e["bbox"];n=(-u[1],u[0]);widths=[]
    for k in range(2):
        if abs(n[k])>1e-6:
            widths.append(((box[1][k]-box[0][k])-abs(u[k])*length)/abs(n[k]))
    if not widths or min(widths)<=tol or max(widths)-min(widths)>tol*2:
        raise ValueError("Wall thickness cannot be determined from its centerline and extents")
    width=sum(widths)/len(widths)
    box_center=((box[0][0]+box[1][0])/2,(box[0][1]+box[1][1])/2)
    shift=dot(sub(box_center,mid),n)
    if abs(dot(sub(box_center,mid),u))>tol:
        raise ValueError("Wall extents do not prove a single straight rectangle")
    a=(a[0]+n[0]*shift,a[1]+n[1]*shift)
    b=(b[0]+n[0]*shift,b[1]+n[1]*shift)
    poly=[(a[0]+n[0]*width/2,a[1]+n[1]*width/2),
          (b[0]+n[0]*width/2,b[1]+n[1]*width/2),
          (b[0]-n[0]*width/2,b[1]-n[1]*width/2),
          (a[0]-n[0]*width/2,a[1]-n[1]*width/2)]
    return poly,a,b,width


def _faces(poly,floor,handle,matrix):
    poly=[transform_point(matrix,p) for p in polygon(poly)]
    sign=1 if sum(cross(a,b) for a,b in zip(poly,poly[1:]+poly[:1]))>0 else -1
    result=[]
    for i,(a,b) in enumerate(zip(poly,poly[1:]+poly[:1])):
        u=unit(sub(b,a))
        result.append({"id":handle+":"+str(i),"source_handle":handle,"floor":floor,
                       "a":a,"b":b,"normal":[sign*u[1],-sign*u[0]]})
    return result


def adapt_source(entities,floors,tolerance):
    result={"faces":[],"openings":[],"obstacles":[],"pending":[]}
    for floor in floors:
        fid=floor["id"];matrix=floor.get("transform",IDENTITY)
        members=[e for e in entities if in_region(e.get("bbox"),floor["region"])]
        for e in entities:
            if e.get("type") in ("TCH_WALL","TCH_COLUMN","TCH_OPENING","INSERT") and not e.get("bbox"):
                result["pending"].append({"floor":fid,"handle":e.get("handle",e.get("h")),"reason":"Source object has no locatable native extents"})
        walls=[]
        for e in members:
            if e.get("type")=="TCH_WALL":
                try:
                    poly,a,b,width=_native_rectangle(e,tolerance)
                    walls.append((a,b,width,e.get("handle",e.get("h"))))
                except (ValueError,KeyError,TypeError):pass
        for e in members:
            handle=e.get("handle",e.get("h","?"));typ=e.get("type")
            try:
                if typ=="TCH_WALL":
                    poly,a,b,width=_native_rectangle(e,tolerance)
                    faces=_faces(poly,fid,handle,matrix)
                    result["obstacles"].append({"id":handle,"floor":fid,"kind":"wall",
                        "polygon":[transform_point(matrix,p) for p in poly]})
                    # Only the two long wall faces. End caps are not default
                    # mounting surfaces without separately verified geometry.
                    result["faces"]+=faces[:1]+faces[2:3]
                elif typ=="TCH_COLUMN":
                    polys=[z["vertices"] for z in e.get("visibleParts",[])
                           if z.get("closed") and z.get("vertices") and
                           not any(abs(v)>1e-12 for v in z.get("bulges",[]))]
                    if not polys:raise ValueError("Column native closed outline missing")
                    poly=max(polys,key=lambda p:abs(sum(cross(a,b) for a,b in zip(p,p[1:]+p[:1]))))
                    transformed=[transform_point(matrix,p) for p in polygon(poly)]
                    result["obstacles"].append({"id":handle,"floor":fid,"polygon":transformed})
                    result["faces"]+=_faces(poly,fid,handle,matrix)
                elif typ=="TCH_OPENING":
                    grips=e.get("grips",[])
                    if len(grips)<3:raise ValueError("Native aperture endpoints missing")
                    a,u,length=frame(grips[1],grips[2]);b=point(grips[2]);n=(-u[1],u[0])
                    candidates=[]
                    for wa,wb,width,wh in walls:
                        _,wu,wl=frame(wa,wb)
                        if abs(abs(dot(wu,u))-1)>1e-6:continue
                        lo,hi=sorted(dot(sub(p,wa),wu) for p in (a,b))
                        distance=abs(cross(sub(a,wa),wu))
                        if min(hi,wl)-max(lo,0)>tolerance and distance<=width/2+tolerance:
                            candidates.append((distance,width,wa,wh))
                    if not candidates:raise ValueError("Aperture lacks a matched actual host wall")
                    candidates.sort(key=lambda v:v[0]);distance,depth,wa,host=candidates[0]
                    shift=dot(sub(wa,a),n)
                    a=(a[0]+n[0]*shift,a[1]+n[1]*shift)
                    b=(b[0]+n[0]*shift,b[1]+n[1]*shift)
                    poly=opening_polygon({"a":a,"b":b,"depth":depth})
                    result["openings"].append({"id":handle,"floor":fid,"a":transform_point(matrix,a),
                        "b":transform_point(matrix,b),"depth":depth,"hostWall":host,
                        "polygon":[transform_point(matrix,p) for p in poly]})
                elif e.get("role")=="obstacle":
                    poly=polygon(e["polygon"])
                    result["obstacles"].append({"id":handle,"floor":fid,"polygon":[transform_point(matrix,p) for p in poly]})
                elif typ=="INSERT" and e.get("role")!="annotation":
                    raise ValueError("Nested architectural/furniture object requires explicit classification and native outline")
            except (ValueError,KeyError,TypeError) as ex:
                result["pending"].append({"floor":fid,"handle":handle,"type":typ,"reason":str(ex)})
    return result


def extract_instances(details,sheets,profiles):
    result=[]
    for root in details.get("blocks",{}).get("*Model_Space",[]):
        if root.get("type") in ("TEXT","MTEXT","TCH_TEXT","TCH_MTEXT","ATTRIB","ATTDEF") or not str(root.get("layer","")).startswith("EQUIP-"):
            continue
        matches=[s for s in sheets if in_region(root.get("bbox"),s["region"])]
        row={"id":root["h"],"handles":[root["h"]],"native_block":root.get("block"),
             "native_layer":root.get("layer"),"geometry_status":"pending"}
        result.append(row)
        if len(matches)!=1:
            row["reason"]="Equipment not assigned to exactly one actual sheet";continue
        sh=matches[0];row.update(sheet=sh["id"],floor=sh["floor"])
        profiles_match=[p for p in profiles if (not p.get("layer") or p["layer"]==root["layer"])
                        and (not p.get("block") or p["block"]==root.get("block"))]
        if len(profiles_match)!=1:
            row["reason"]="Missing/ambiguous native symbol profile";continue
        profile=profiles_match[0];row["kind"]=profile["kind"]
        if profile["extractor"] in ("semicircle","reviewed-semicircle-chord"):
            mount=(socket_mount(details,root) if profile["extractor"]=="semicircle" else
                   socket_mount_from_chord(details,root,profile["localTolerance"]))
            if mount["status"]!="passed":
                row["reason"]=mount["reason"];continue
            m=sh.get("transform",IDENTITY)
            edge=[transform_point(m,p) for p in mount["edge"]]
            tangent=unit(sub(edge[1],edge[0]));normal=(-tangent[1],tangent[0])
            origin=transform_point(m,[0,0]);endpoint=transform_point(m,mount["normal"])
            if dot(normal,sub(endpoint,origin))<0:normal=(-normal[0],-normal[1])
            row.update(geometry_status="passed",mountingEdge=edge,normal=normal,
                       footprint=[transform_point(m,p) for p in mount["footprint"]],
                       mountingEvidence={"nativeArc":mount["arc"],"blockChain":mount["chain"]})
        elif profile["extractor"]=="declared-native-edge":
            try:
                primitives=list(flatten(details,root))
                def select(handle):
                    found=[(e,m) for e,m,chain in primitives if e["h"]==handle]
                    if len(found)!=1:raise ValueError("Native profile primitive missing/ambiguous: "+handle)
                    return found[0]
                e,m=select(profile["primitive"])
                if e["type"]!="LINE" or len(e.get("vertices",[]))!=2:
                    raise ValueError("Profile primitive is not an actual native line")
                matrix=compose(sh.get("transform",IDENTITY),m)
                edge=[transform_point(matrix,p) for p in e["vertices"]]
                # Local normal is a profile's reviewed orientation, never the
                # project's desired location or generated point normal.
                tangent=unit(sub(edge[1],edge[0]));normal=(-tangent[1],tangent[0])
                n=profile["normal"];zero=transform_point(matrix,[0,0]);end=transform_point(matrix,n)
                if dot(normal,sub(end,zero))<0:normal=(-normal[0],-normal[1])
                row.update(geometry_status="passed",mountingEdge=edge,normal=normal,
                           mountingEvidence={"nativeLine":e["h"],"profile":profile})
                if profile.get("bodyPrimitive"):
                    body,bm=select(profile["bodyPrimitive"])
                    if body["type"] not in ("LWPOLYLINE","POLYLINE") or not body.get("closed") or any(abs(v)>1e-12 for v in body.get("bulges",[])):
                        raise ValueError("Native body requires a closed straight-edge polygon")
                    matrix=compose(sh.get("transform",IDENTITY),bm)
                    row["footprint"]=[transform_point(matrix,p) for p in polygon(body["vertices"])]
                    row["mountingEvidence"]["nativeBody"]=body["h"]
            except (ValueError,KeyError,TypeError) as ex:
                row.update(geometry_status="pending",reason=str(ex))
                row.pop("mountingEdge",None);row.pop("footprint",None)
        else:row["reason"]="Unsupported native extractor"
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source-native",type=Path,required=True)
    p.add_argument("--saved-native",type=Path,required=True)
    p.add_argument("--config",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    args=p.parse_args()
    read=lambda f:json.loads(f.read_text("utf-8-sig"))
    cfg=read(args.config);source=adapt_source(read(args.source_native),cfg["floors"],cfg["tolerance"])
    sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
    source["provenance"]={"native_source":{"path":str(args.source_native.resolve()),"sha256":sha(args.source_native)},
        "config":{"path":str(args.config.resolve()),"sha256":sha(args.config)},"source_drawings":cfg["source_drawings"]}
    args.output.mkdir(parents=True,exist_ok=True)
    (args.output/"source-geometry.json").write_text(json.dumps(source,ensure_ascii=False,indent=2),"utf8")
    actual={"instances":extract_instances(read(args.saved_native),cfg["sheets"],cfg["profiles"]),
            "drawing_sha256":cfg["drawing_sha256"],"readback_sha256":sha(args.saved_native),
            "source_geometry_sha256":sha(args.output/"source-geometry.json")}
    (args.output/"actual-geometry.json").write_text(json.dumps(actual,ensure_ascii=False,indent=2),"utf8")
    print(json.dumps({"faces":len(source["faces"]),"openings":len(source["openings"]),
        "unsupportedSource":len(source["pending"]),"actualInstances":len(actual["instances"])},ensure_ascii=False))


if __name__=="__main__":main()
