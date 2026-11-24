"""Fail-closed delivery gate: file identity, independent inventories and all checks."""
from __future__ import annotations
import argparse
from collections import Counter
import hashlib
import json
import math
import struct
import zlib
from pathlib import Path

CORE_CHECKS=("symbols","circuits","geometry","operation_and_clearance","visual","presentation","background")
POINT_CHECKS={"symbols","circuits","geometry","operation_and_clearance","visual"}


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _read(path):
    return json.loads(Path(path).read_text("utf-8-sig"))


def png_dimensions(path):
    """Verify noninterlaced 8-bit raster review evidence and return pixel size."""
    data=Path(path).read_bytes()
    if data[:8]!=b"\x89PNG\r\n\x1a\n":raise ValueError("Visual evidence must be a rendered PNG")
    at=8;size=None;compressed=[];ended=False
    while at+12<=len(data):
        length=struct.unpack(">I",data[at:at+4])[0]
        typ=data[at+4:at+8];chunk=data[at+8:at+8+length]
        if len(chunk)!=length or at+12+length>len(data):raise ValueError("Truncated PNG")
        crc=struct.unpack(">I",data[at+8+length:at+12+length])[0]
        if zlib.crc32(typ+chunk)&0xffffffff!=crc:raise ValueError("PNG CRC mismatch")
        if typ==b"IHDR":
            if size or length!=13:raise ValueError("Invalid PNG header")
            w,h,depth,color,cm,fm,interlace=struct.unpack(">IIBBBBB",chunk)
            if not w or not h or w*h>100_000_000 or depth!=8 or color not in (0,2,4,6) or cm or fm or interlace:
                raise ValueError("Unsupported PNG review raster")
            size=(w,h,{0:1,2:3,4:2,6:4}[color])
        elif typ==b"IDAT":compressed.append(chunk)
        elif typ==b"IEND":ended=True;break
        at+=length+12
    if not ended or not size or not compressed:raise ValueError("Incomplete PNG")
    w,h,c=size;expected=h*(1+w*c)
    dec=zlib.decompressobj();raw=dec.decompress(b"".join(compressed),expected+1)
    if len(raw)!=expected or not dec.eof:raise ValueError("Invalid PNG scanlines")
    return w,h

def bound_inputs(manifest_path):
    """Compute identities from actual artifacts; no self-hash embedded in actual."""
    base=Path(manifest_path).resolve().parent
    m=_read(manifest_path);paths={};bindings={}
    def add(key,ref):
        path=Path(ref["path"])
        if not path.is_absolute():path=base/path
        if not path.is_file() or sha256(path)!=ref["sha256"]:
            raise ValueError("Artifact missing/stale: "+key)
        if key in bindings:raise ValueError("Duplicate artifact identity: "+key)
        paths[key]=path.resolve();bindings[key]=ref["sha256"]
    for key in ("drawing","readback","expected","actual","geometry_source"):
        add(key,m[key])
    for key,ref in m["sources"].items():add(key,ref)
    for key,ref in m["rules"].items():add("rule:"+key,ref)
    geom=_read(paths["geometry_source"]);provenance=geom["provenance"]
    add("geometry-native",provenance["native_source"])
    add("geometry-config",provenance["config"])
    return bindings,paths

def validate_delivery(manifest_path):
    base=Path(manifest_path).resolve().parent
    errors=[];pending=[];reports={}
    result={"passed":False,"reviewDraftReady":False,"constructionReady":False,
            "executionStatus":"passed","coverage":{"passed":False},"errors":errors,"pending":pending,"checks":reports}

    def artifact(ref,label):
        if not isinstance(ref,dict) or not ref.get("path") or not ref.get("sha256"):
            errors.append("Missing artifact identity: "+label);return None
        path=Path(ref["path"])
        if not path.is_absolute():path=base/path
        if not path.is_file():
            errors.append("Missing artifact: "+label);return None
        if sha256(path)!=ref["sha256"]:
            errors.append("Hash mismatch: "+label);return None
        return path

    try:
        m=_read(manifest_path)
        if m.get("schema")!=1 or m.get("mode") not in ("review","construction"):
            raise ValueError("Unsupported/missing schema or release mode")
        bindings={}
        drawing=artifact(m.get("drawing"),"drawing")
        if not drawing:return result
        dhash=m["drawing"]["sha256"];bindings["drawing"]=dhash
        for group,prefix in (("sources",""),("rules","rule:")):
            if not isinstance(m.get(group),dict) or not m[group]:
                errors.append("Missing "+group)
            for name,ref in m.get(group,{}).items():
                if prefix+name in bindings or name in ("readback","actual","expected","geometry_source","geometry-native","geometry-config"):
                    errors.append("Reserved/duplicate input identity: "+name);continue
                if artifact(ref,group+":"+name):bindings[prefix+name]=ref["sha256"]
        contents={}
        for name in ("readback","expected","actual","geometry_source"):
            path=artifact(m.get(name),name)
            if path:
                contents[name]=_read(path);bindings[name]=m[name]["sha256"]
        if len(contents)!=4:return result
        native,expected,actual=(contents[k] for k in ("readback","expected","actual"))
        for name,item in (("readback",native),("actual",actual)):
            if item.get("drawing_sha256")!=dhash:errors.append(name+" is not bound to this DWG")
        if native.get("errors"):
            pending.append("Native export contains unextracted entities")
        if any(e.get("type")=="ACAD_PROXY_ENTITY" for entries in native.get("blocks",{}).values() for e in entries):
            pending.append("Native proxy entities require a supported readback")
        source_binding={k:v["sha256"] for k,v in m.get("sources",{}).items()}
        geometry_provenance=contents["geometry_source"].get("provenance",{})
        if geometry_provenance.get("source_drawings")!=source_binding:
            errors.append("Normalized geometry lacks matching source drawing provenance")
        for key,field in (("geometry-native","native_source"),("geometry-config","config")):
            ref=geometry_provenance.get(field)
            if artifact(ref,key):bindings[key]=ref["sha256"]
        if actual.get("readback_sha256")!=m["readback"]["sha256"] or actual.get("source_geometry_sha256")!=m["geometry_source"]["sha256"]:
            errors.append("Actual geometry lacks saved-native/source-geometry provenance")
        coverage_errors=[]
        if not source_binding or expected.get("basis")!=source_binding:
            coverage_errors.append("Expected inventory lacks source-drawing hash provenance")
        requirements=expected.get("requirements",[])
        instances=actual.get("instances",[])
        if not requirements or not instances:
            coverage_errors.append("Empty expected or actual inventory")
        rid=[r.get("id") for r in requirements];ids=[r.get("id") for r in instances]
        if None in rid or len(rid)!=len(set(rid)):coverage_errors.append("Missing/duplicate requirement IDs")
        if None in ids or len(ids)!=len(set(ids)):coverage_errors.append("Missing/duplicate actual IDs")
        reqmap={r.get("id"):r for r in requirements};counts=Counter()
        handle_counts=Counter()
        for v in instances:
            handles=v.get("handles",[])
            if not handles or len(handles)!=len(set(handles)):
                coverage_errors.append("Missing/duplicate handles within "+str(v.get("id")))
            handle_counts.update(handles)
            r=reqmap.get(v.get("requirement_id"))
            if r is None:
                coverage_errors.append("Unassigned actual instance "+str(v.get("id")));continue
            if any(v.get(k)!=r.get(k) or v.get(k) is None for k in ("sheet","floor","room","kind")):
                coverage_errors.append("Requirement classification differs: "+str(v.get("id")))
            counts[r["id"]]+=1
        if any(n!=1 for n in handle_counts.values()):
            coverage_errors.append("A native handle belongs to multiple actual instances")
        for r in requirements:
            q=r.get("quantity")
            if not isinstance(q,int) or isinstance(q,bool) or q<0 or not r.get("basis"):
                coverage_errors.append("Requirement lacks independent quantity/basis: "+str(r.get("id")))
            elif counts[r["id"]]!=q:
                coverage_errors.append("Expected/actual quantity mismatch: "+str(r["id"]))
        # Discover all actual top-level equipment instances, rather than trusting
        # the generated design list to tell us what exists in the saved DWG.
        roots=native.get("blocks",{}).get("*Model_Space")
        if not isinstance(roots,list):coverage_errors.append("Missing native ModelSpace inventory");roots=[]
        label_types={"TEXT","MTEXT","TCH_TEXT","TCH_MTEXT","ATTRIB","ATTDEF"}
        equipment={e.get("h") for e in roots if e.get("type") not in label_types and str(e.get("layer","")).startswith("EQUIP-")}
        model_handles={e.get("h") for e in roots}
        declared=set(handle_counts)
        missing_native=declared-model_handles
        if missing_native:coverage_errors.append("Declared handles absent from saved ModelSpace: "+str(sorted(missing_native)))
        exclusions=actual.get("exclusions",[])
        excluded=set()
        for e in exclusions:
            if not e.get("handle") or not e.get("reason") or not e.get("evidence"):
                coverage_errors.append("Unsubstantiated native exclusion");continue
            excluded.add(e["handle"])
        if len(excluded)!=len(exclusions) or declared&excluded or excluded-model_handles:
            coverage_errors.append("Invalid/duplicate/overlapping exclusions")
        unmapped=equipment-declared-excluded
        if unmapped:coverage_errors.append("Unmapped saved equipment instances: "+str(sorted(unmapped)))
        sheets=m.get("sheets",[])
        if not sheets or len(sheets)!=len(set(sheets)):coverage_errors.append("Missing/duplicate required sheet list")
        if any(v.get("sheet") not in sheets for v in instances):
            coverage_errors.append("Actual instance references an undeclared sheet")
        result["coverage"]={"passed":not coverage_errors,"errors":coverage_errors,
                            "requirements":len(requirements),"actualInstances":len(instances),
                            "nativeEquipment":len(equipment),"mappedNativeHandles":len(declared),
                            "unmappedHandles":sorted(unmapped)}
        errors.extend(coverage_errors)
        for name in CORE_CHECKS:
            ref=m.get("checks",{}).get(name)
            path=artifact(ref,"check:"+name)
            if not path:
                reports[name]={"status":"pending","reason":"Required report missing or invalid"}
                continue
            report=_read(path);problems=[]
            if report.get("errors") or report.get("passed") is False:
                problems.append("A passed heading cannot override recorded errors/failure")
            if name=="geometry" and report.get("acceptanceEligible") is not True:
                problems.append("Support-only/incomplete geometry is not full acceptance evidence")
            if report.get("drawing_sha256")!=dhash or report.get("inputs")!=bindings:
                problems.append("Report input hashes are missing/stale")
            status=report.get("status")
            if status not in ("passed","failed","pending"):
                problems.append("Unrecognized/missing report status");status="pending"
            if not report.get("evidence"):
                problems.append("Report has no execution evidence")
            if name in POINT_CHECKS:
                points=report.get("points",[])
                point_ids=[v.get("id") for v in points]
                if len(point_ids)!=len(set(point_ids)) or set(point_ids)!=set(ids):
                    problems.append("Per-point check coverage differs from saved inventory")
                for v in points:
                    if v.get("status")!="passed" or not v.get("evidence"):
                        problems.append("Point is failed/pending or lacks evidence: "+str(v.get("id")))
            if name=="visual":
                artifacts=report.get("artifacts",{});valid={}
                for key,ref in artifacts.items():
                    image_path=artifact(ref,"visual:"+key)
                    try:valid[key]=png_dimensions(image_path) if image_path else None
                    except (OSError,ValueError,struct.error,zlib.error) as ex:
                        valid[key]=None;problems.append(str(ex))
                def visual_evidence(e):
                    region=e.get("region",[]) if isinstance(e,dict) else []
                    return (isinstance(e,dict) and valid.get(e.get("artifact"),False)
                        and e.get("page")==1
                        and isinstance(region,list) and len(region)==4
                        and all(isinstance(x,(int,float)) and math.isfinite(x) for x in region)
                        and 0<=region[0]<region[2]<=valid[e["artifact"]][0]
                        and 0<=region[1]<region[3]<=valid[e["artifact"]][1])
                pages=report.get("pages",[])
                names=[p.get("sheet") for p in pages]
                if len(names)!=len(set(names)) or set(names)!=set(sheets):
                    problems.append("Visual page coverage incomplete")
                for v in pages+report.get("points",[]):
                    if v.get("status")!="passed" or not visual_evidence(v.get("evidence")):
                        problems.append("Missing visual artifact, page or local region")
                page_map={p.get("sheet"):p.get("evidence",{}) for p in pages}
                instance_map={v.get("id"):v for v in instances}
                for p in report.get("points",[]):
                    sheet=instance_map.get(p.get("id"),{}).get("sheet")
                    pe=p.get("evidence",{});se=page_map.get(sheet,{})
                    if not isinstance(pe,dict) or not isinstance(se,dict) or (pe.get("artifact"),pe.get("page"))!=(se.get("artifact"),se.get("page")):
                        problems.append("Point visual evidence refers to another sheet")
            if status=="failed":
                errors.append("Check failed: "+name)
            elif status=="pending":
                pending.append("Check pending: "+name)
            if problems:
                errors.extend(name+": "+p for p in problems)
            reports[name]={"status":status if not problems else "pending","errors":problems,
                           "path":str(path),"sha256":ref["sha256"]}
        if any(r["status"]!="passed" for r in reports.values()):
            pending.append("Some mandatory checks have not passed")
        engineering=m.get("engineering",{})
        es=engineering.get("status")
        if es=="failed":errors.append("Known engineering failure must not be downgraded to pending")
        if es not in ("passed","pending","failed"):
            pending.append("Engineering status missing")
        elif es!="passed" and not engineering.get("items"):
            pending.append("Engineering pending/failed items not listed")
        engineering_verified=False
        if es=="passed":
            erpath=artifact(engineering.get("report"),"engineering-report")
            if erpath:
                er=_read(erpath)
                engineering_verified=(er.get("status")=="passed" and er.get("inputs")==bindings
                    and er.get("passed") is not False
                    and er.get("drawing_sha256")==dhash and bool(er.get("evidence"))
                    and not er.get("errors") and not er.get("pending"))
            if not engineering_verified:pending.append("Engineering approval evidence missing/stale")
        result["reviewDraftReady"]=not errors and not pending
        result["constructionReady"]=result["reviewDraftReady"] and engineering_verified and not engineering.get("items")
        result["passed"]=result["constructionReady"] if m["mode"]=="construction" else result["reviewDraftReady"]
        result.update(mode=m["mode"],engineering=engineering,drawing_sha256=dhash,
                      status="passed" if result["passed"] else "failed" if errors else "pending")
        return result
    except (OSError,ValueError,KeyError,TypeError,AttributeError) as ex:
        errors.append(str(ex));result.update(status="failed",executionStatus="failed");return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest",type=Path,required=True)
    parser.add_argument("--report",type=Path,required=True)
    args=parser.parse_args()
    report=validate_delivery(args.manifest)
    args.report.write_text(json.dumps(report,ensure_ascii=False,indent=2),"utf8")
    print(json.dumps({k:v for k,v in report.items() if k!="checks"},ensure_ascii=False))
    return 0 if report["passed"] else 1


if __name__=="__main__":raise SystemExit(main())
