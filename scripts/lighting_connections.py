"""Plan WIRE-照明 endpoint pairs for one verified household/circuit at a time."""
from math import dist, hypot, isfinite


def validate_supply(root, lamp_ids, pairs):
    """Accept ordered supply pairs only. No switch or control edge proves supply."""
    lamps = set(lamp_ids)
    reached = {root}
    for source, new_lamp in pairs:
        if source not in reached or new_lamp not in lamps or new_lamp in reached:
            raise ValueError(f"Invalid or repeated lamp feed: {source} -> {new_lamp}")
        if source == root and len(reached) > 1:
            raise ValueError("Multiple starts from the same lighting branch")
        reached.add(new_lamp)
    if reached != lamps | {root}:
        raise ValueError(f"Missing lamp feeds: {sorted(lamps - reached)}")


def _overlaps(a, b, c, d, tol):
    """Positive-length collinear overlap, disregarding shared endpoints."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = hypot(dx, dy)
    ux, uy = dx / length, dy / length
    offsets = [(p[0] - a[0], p[1] - a[1]) for p in (c, d)]
    if any(abs(x * uy - y * ux) > tol for x, y in offsets):
        return False
    lo, hi = sorted(x * ux + y * uy for x, y in offsets)
    return min(length, hi) - max(0, lo) > tol


def plan_lighting(root, lamps, switches, points, groups, *, legal, rank=None, tol=1e-6):
    """Return supply edges, physical control drops, and per-key control intents.

    IDs belong to one circuit. points are 2D node positions. legal(a,b) checks
    the project's installable route by ID. Optional rank(a,b) gives a lower
    score to a preferred legal route. groups use targets, keys [(switch,key)],
    and mode single/dual. Clip edges to native symbol contacts when drawing.
    """
    lamps, switches = list(lamps), list(switches)
    ids = [root, *lamps, *switches]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate device or circuit root ID")
    if tol <= 0 or not isfinite(tol):
        raise ValueError("Invalid model tolerance")
    for node in ids:
        if len(points[node]) != 2 or not all(isfinite(x) for x in points[node]):
            raise ValueError(f"Invalid 2D position for {node}")
    drawn = []
    def choose(candidates):
        choices = []
        for a, b in candidates:
            p, q = points[a], points[b]
            length = dist(p, q)
            if length <= tol or not legal(a, b):
                continue
            if any(_overlaps(p, q, points[i], points[j], tol) for i, j in drawn):
                continue
            choices.append((rank(a, b) if rank else 0, length, a, b))
        return min(choices)[-2:] if choices else None

    remaining = set(lamps)
    sources = {root}
    while remaining:
        edge = choose((a, b) for a in sources for b in remaining)
        if edge is None:
            raise ValueError(f"No legal direct feed for remaining lamps: {sorted(remaining)}")
        source, lamp = edge
        drawn.append((source, lamp))
        remaining.remove(lamp)
        sources.discard(root)
        sources.add(lamp)
    supply = drawn.copy()
    validate_supply(root, lamps, supply)

    control = []
    key_targets = {}
    owned = set()
    switch_set = set(switches)
    parents = {lamp: source for source, lamp in supply}
    def lamp_path(a, b):
        def ancestors(node):
            chain = [node]
            while node in parents:
                node = parents[node]
                chain.append(node)
            return chain
        first, second = ancestors(a), ancestors(b)
        common = next(node for node in first if node in second)
        return first[:first.index(common) + 1] + second[:second.index(common)][::-1]

    for group in groups:
        targets = tuple(sorted(group["targets"]))
        keys = [tuple(k) for k in group["keys"]]
        count = {"single": 1, "dual": 2}.get(group["mode"])
        if (not targets or not set(targets) <= set(lamps) or owned.intersection(targets)
                or len(targets) != len(set(targets))):
            raise ValueError(f"Invalid or repeated control group: {targets}")
        if len(keys) != count or len({s for s, k in keys}) != count:
            raise ValueError(f"Invalid operating positions: {keys}")
        owned.update(targets)
        for switch, key in keys:
            if switch not in switch_set or key < 1 or (switch, key) in key_targets:
                raise ValueError(f"Unknown or duplicate switch key: {switch}, {key}")
            edge = choose((switch, lamp) for lamp in targets)
            if edge:
                drawn.append(edge)
                control.append(edge)
                route = list(edge)
            else:
                # Another key at this panel may already reach a real lamp box.
                # Route the distinct switched conductor through existing segments.
                routes = [[switch] + lamp_path(entry, lamp) for s, entry in control
                          if s == switch for lamp in targets]
                if not routes:
                    raise ValueError(f"No legal control connection for {switch}/{key}")
                route = min(routes, key=lambda r: (sum(dist(points[a], points[b])
                            for a, b in zip(r, r[1:])), r))
            key_targets[switch, key] = {"entryLamp": route[-1], "targets": targets,
                                        "route": route}
    if owned != set(lamps) or {s for s, k in key_targets} != switch_set:
        raise ValueError("Incomplete lamp or switch control assignments")
    return {"supply": supply, "control": control, "keys": key_targets}
