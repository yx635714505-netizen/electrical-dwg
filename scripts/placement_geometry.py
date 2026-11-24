"""Finite 2D support faces, openings, affine transforms; no project coordinates."""
from __future__ import annotations
import math

IDENTITY = (1., 0., 0., 1., 0., 0.)


def point(value):
    if len(value) < 2 or not all(math.isfinite(float(v)) for v in value[:2]):
        raise ValueError("Expected a finite 2D point")
    return (float(value[0]), float(value[1]))


def sub(a, b):
    return (a[0]-b[0], a[1]-b[1])


def dot(a, b):
    return a[0]*b[0]+a[1]*b[1]


def cross(a, b):
    return a[0]*b[1]-a[1]*b[0]


def unit(v):
    v = point(v)
    length = math.hypot(*v)
    if length <= 1e-12:
        raise ValueError("Degenerate direction")
    return (v[0]/length, v[1]/length)


def frame(a, b):
    a, b = point(a), point(b)
    v = sub(b, a)
    return a, unit(v), math.hypot(*v)


def transform_point(matrix, p):
    x, y = point(p)
    a,b,c,d,tx,ty = matrix
    return point((a*x+c*y+tx, b*x+d*y+ty))


def compose(parent, child):
    a,b,c,d,x,y = parent
    e,f,g,h,u,v = child
    return (a*e+c*f,b*e+d*f,a*g+c*h,b*g+d*h,a*u+c*v+x,b*u+d*v+y)


def block_transform(entity):
    sx, sy = entity.get("scale", [1, 1])[:2]
    x, y = entity.get("pos", [0, 0])[:2]
    angle = entity.get("angle", 0)
    c, s = math.cos(angle), math.sin(angle)
    values = (sx*c, sx*s, -sy*s, sy*c, x, y)
    if not all(math.isfinite(float(v)) for v in values) or abs(sx*sy) < 1e-15:
        raise ValueError("Invalid block transform")
    return values


def polygon(value):
    points = [point(p) for p in value]
    if len(points) > 1 and points[0] == points[-1]:
        points.pop()
    if len(points) < 3 or abs(sum(cross(a,b) for a,b in zip(points,points[1:]+points[:1]))) < 1e-12:
        raise ValueError("Degenerate polygon")
    edges=list(zip(points,points[1:]+points[:1]))
    if any(math.hypot(*sub(b,a)) <= 1e-12 for a,b in edges):
        raise ValueError("Zero-length polygon edge")
    def on_segment(p,a,b):
        return abs(cross(sub(b,a),sub(p,a))) <= 1e-12 and dot(sub(p,a),sub(p,b)) <= 1e-12
    for i,(a,b) in enumerate(edges):
        for j,(c,d) in enumerate(edges[i+1:],i+1):
            if j==i+1 or (i==0 and j==len(edges)-1):continue
            ab_c=cross(sub(b,a),sub(c,a));ab_d=cross(sub(b,a),sub(d,a))
            cd_a=cross(sub(d,c),sub(a,c));cd_b=cross(sub(d,c),sub(b,c))
            if (ab_c*ab_d < 0 and cd_a*cd_b < 0) or any((on_segment(c,a,b),on_segment(d,a,b),on_segment(a,c,d),on_segment(b,c,d))):
                raise ValueError("Self-intersecting polygon")
    return points


def point_segment_distance(p, a, b):
    a,u,length = frame(a,b)
    t = max(0, min(length, dot(sub(point(p),a),u)))
    return math.hypot(p[0]-a[0]-u[0]*t,p[1]-a[1]-u[1]*t)


def inside(p, poly, tol):
    if any(point_segment_distance(p,a,b) <= tol for a,b in zip(poly,poly[1:]+poly[:1])):
        return True
    result = False
    x,y = p
    for a,b in zip(poly,poly[1:]+poly[:1]):
        if (a[1] > y) != (b[1] > y) and x < (b[0]-a[0])*(y-a[1])/(b[1]-a[1])+a[0]:
            result = not result
    return result


def segment_polygon_spans(a, b, poly, tol):
    """Intervals in distance along a finite segment within/on a simple polygon."""
    if not math.isfinite(tol) or tol <= 0:
        raise ValueError("Positive tolerance required")
    poly = polygon(poly)
    a,u,length = frame(a,b)
    breaks = [0., length]
    for p,q in zip(poly,poly[1:]+poly[:1]):
        v = sub(q,p)
        divisor = cross(u,v)
        if abs(divisor) < 1e-12:
            if abs(cross(sub(p,a),u)) <= tol:
                breaks += [max(0,min(length,dot(sub(t,a),u))) for t in (p,q)]
            continue
        t = cross(sub(p,a),v)/divisor
        s = cross(sub(p,a),u)/divisor
        if -tol <= t <= length+tol and -1e-9 <= s <= 1+1e-9:
            breaks.append(max(0,min(length,t)))
    breaks = sorted(set(breaks))
    intervals = []
    for lo,hi in zip(breaks,breaks[1:]):
        mid = (lo+hi)/2
        if hi-lo > 1e-9 and inside((a[0]+u[0]*mid,a[1]+u[1]*mid),poly,tol):
            intervals.append((lo,hi))
    return merge(intervals, 1e-8)


def opening_polygon(opening):
    if "polygon" in opening:
        return polygon(opening["polygon"])
    a,u,length = frame(opening["a"],opening["b"])
    b = point(opening["b"])
    depth = float(opening["depth"])
    if not math.isfinite(depth) or depth <= 0:
        raise ValueError("Opening depth is missing/invalid")
    n = (-u[1]*depth/2,u[0]*depth/2)
    return [(a[0]+n[0],a[1]+n[1]),(b[0]+n[0],b[1]+n[1]),
            (b[0]-n[0],b[1]-n[1]),(a[0]-n[0],a[1]-n[1])]


def merge(intervals, tol):
    result = []
    for lo,hi in sorted(intervals):
        if result and lo <= result[-1][1]+tol:
            result[-1] = (result[-1][0],max(hi,result[-1][1]))
        else:
            result.append((lo,hi))
    return result


def blocked_spans(face, openings, obstacles, tol):
    spans = []
    for obj in openings:
        spans += segment_polygon_spans(face["a"],face["b"],opening_polygon(obj),tol)
    for obj in obstacles:
        spans += segment_polygon_spans(face["a"],face["b"],obj["polygon"],tol)
    return merge(spans,tol)


def usable_spans(face, openings, obstacles, tol):
    _,_,length = frame(face["a"],face["b"])
    cursor, result = 0., []
    for lo,hi in blocked_spans(face,openings,obstacles,tol):
        if lo > cursor+tol:
            result.append((cursor,lo))
        cursor = max(cursor,hi)
    if length > cursor+tol:
        result.append((cursor,length))
    return result


def check_edge(edge, normal, face, openings, obstacles, tol):
    if not math.isfinite(tol) or tol <= 0:
        raise ValueError("Positive tolerance required")
    a,u,length = frame(face["a"],face["b"])
    e0,e1 = map(point,edge)
    frame(e0,e1)
    lo,hi = sorted(dot(sub(p,a),u) for p in (e0,e1))
    reasons = []
    if max(abs(cross(sub(p,a),u)) for p in (e0,e1)) > tol:
        reasons.append("not_on_face")
    if lo < -tol or hi > length+tol:
        reasons.append("edge_exceeds_face")
    if dot(unit(normal),unit(face["normal"])) < 1-1e-6:
        reasons.append("wrong_side")
    available = usable_spans(face,openings,obstacles,tol)
    for label,objects,make in (("opening_overlap",openings,opening_polygon),
                               ("obstacle_overlap",obstacles,lambda x:x["polygon"])):
        for obj in objects:
            spans = segment_polygon_spans(face["a"],face["b"],make(obj),tol)
            if any(min(hi,y)-max(lo,x) > tol for x,y in spans):
                reasons.append(label)
                break
    if not any(x-tol <= lo and hi <= y+tol for x,y in available):
        reasons.append("no_continuous_support")
    return {"status":"failed" if reasons else "passed","face":face.get("id"),
            "reasons":reasons,"edgeInterval":[lo,hi],"usableSpans":available}


def polygons_overlap(a, b, tol):
    """Positive-area overlap for convex native footprints; touching is permitted."""
    a,b = polygon(a),polygon(b)
    for poly in (a,b):
        turns=[cross(sub(poly[(i+1)%len(poly)],poly[i]),
                     sub(poly[(i+2)%len(poly)],poly[(i+1)%len(poly)])) for i in range(len(poly))]
        if any(t>1e-10 for t in turns) and any(t<-1e-10 for t in turns):
            raise ValueError("Concave footprint requires explicit decomposition/review")
    for poly in (a,b):
        for p,q in zip(poly,poly[1:]+poly[:1]):
            v=unit(sub(q,p));n=(-v[1],v[0])
            av=[dot(v,n) for v in a];bv=[dot(v,n) for v in b]
            if min(max(av),max(bv))-max(min(av),min(bv)) <= tol:
                return False
    return True
