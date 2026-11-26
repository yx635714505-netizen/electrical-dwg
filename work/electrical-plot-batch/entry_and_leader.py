"""Architectural door hand and local native leader placement, in drawing coordinates."""
import math


def swing_hand(jambs, leaf_lines):
    """Use a jamb-attached open leaf. Ambiguous and double leaves need separate interpretation."""
    a, b = jambs
    width = math.dist(a, b)
    if width <= 0:
        raise ValueError("门洞净宽无效")
    axis = [(b[k]-a[k])/width for k in (0, 1)]
    matches = []
    for i, jamb in enumerate(jambs):
        for handle, endpoints in leaf_lines:
            for root, tip in (endpoints, endpoints[::-1]):
                length = math.dist(root, tip)
                if not .65*width <= length <= 1.08*width or math.dist(root, jamb) > .065*width:
                    continue
                if abs(sum(axis[k]*(tip[k]-root[k]) for k in (0,1))) < .14*length:
                    matches.append((math.dist(root,jamb),i,handle,tip))
    if len({m[1] for m in matches}) != 1:
        raise ValueError("门扇依据无法唯一确定铰侧，须对照原生门或门弧")
    _, index, handle, tip = min(matches)
    return dict(hinge=jambs[index], latch=jambs[1-index], openLeaf=tip, leafSource=handle)


def latch_side(point, door):
    axis = [b-a for a,b in zip(door["hinge"], door["latch"])]
    return sum(v*(p-l) for v,p,l in zip(axis,point,door["latch"])) >= -1


def intersects(a, b, box):
    lo, hi = 0., 1.
    for i in (0,1):
        diff = b[i]-a[i]
        if abs(diff)<1e-9:
            if not box[0][i] <= a[i] <= box[1][i]:
                return False
        else:
            u,v=sorted(((box[0][i]-a[i])/diff,(box[1][i]-a[i])/diff))
            lo,hi=max(lo,u),min(hi,v)
            if lo>hi:
                return False
    return True


def crosses(a,b,c,d):
    def side(p,q,r):
        return (q[0]-p[0])*(r[1]-p[1])-(q[1]-p[1])*(r[0]-p[0])
    if any(max(a[i],b[i])+1e-7<min(c[i],d[i]) or max(c[i],d[i])+1e-7<min(a[i],b[i]) for i in (0,1)):
        return False
    return side(a,b,c)*side(a,b,d)<=0 and side(c,d,a)*side(c,d,b)<=0


def nearest_note(tip, candidates, boxes, lines):
    """Candidates carry measured text/shelf rectangles and native knee coordinates."""
    ranked=[]
    for knee, rect, payload in candidates:
        if any(all(rect[0][i]<=b[1][i] and b[0][i]<=rect[1][i] for i in (0,1)) or intersects(tip,knee,b) for b in boxes):
            continue
        if any(intersects(a,b,rect) or crosses(tip,knee,a,b) for a,b in lines):
            continue
        ranked.append((math.dist(tip,knee),len(ranked),payload))
    if not ranked:
        raise ValueError("引注点周边无完整可读位置，调整局部排图")
    return min(ranked)[2]
