"""Find an In2 route for CELL18 that keeps clear of the isoSPI band (read-only).

    python _tools/kicad_sch/cell18_detour.py [--pcb FILE] [--grid 0.1] [--json OUT]

Works on a copy of the Lean board (default: exports/cell18_detour/). It does not write the board.
The search is on In2.Cu only, from the CELL18 top via to the stub via above R302, on a grid.

Blocked cells (CELL18 centreline may not enter them):
  - every port track (ISOA_*/ISOB_*) on any layer, plus clearance: it must not cross the band
    in plan view at all, since a crossing on any other layer is what the check counts;
  - every other In2 track and every via (not CELL18): width/2 + 0.2 mm clearance;
  - every In2 zone (VCOLL and others): outline plus 0.6 mm (the VCOLL range rule);
  - the board edge (0.5 mm) and the M2 hole keep-outs (HOLE_KEEP from lean_place).
Output: waypoints in mm, after line-of-sight simplification, to paste into lean_route.supply().
"""
import argparse
import heapq
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import isospi_shield_check as m  # noqa: E402  (parser and geometry helpers)

REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
DEFAULT = os.path.join(REPO, "exports", "cell18_detour", "adbms1818-slave-18s-lean.kicad_pcb")
W, H = 70.0, 32.0
HOLES = [(2.5, 2.5), (W - 2.5, 2.5), (2.5, H - 2.5), (W - 2.5, H - 2.5)]
HOLE_KEEP = 2.75
CELL_W = 0.25
CLR = 0.2
VCOLL_CLR = 0.6
BAND_CHIP = {"/IPA", "/IMA", "/IPB", "/IMB"}  # chip-side isoSPI nets: also part of the band


def seg_dist(px, py, a, b):
    return m.seg_point_dist(px, py, a[0], a[1], b[0], b[1])


def load(path):
    with open(path, encoding="utf-8") as f:
        root = m.parse_sexpr(f.read())
    tracks, vias, zones = [], [], []
    for node in root[1:]:
        if not isinstance(node, list) or not node:
            continue
        if node[0] == "segment":
            st, en = m.child(node, "start"), m.child(node, "end")
            tracks.append({"a": (float(st[1]), float(st[2])), "b": (float(en[1]), float(en[2])),
                           "w": float(m.child(node, "width")[1]),
                           "layer": m.s_str(m.child(node, "layer")[1]),
                           "net": m.s_str(m.child(node, "net")[1]) if m.child(node, "net") else ""})
        elif node[0] == "via":
            at = m.child(node, "at")
            size = float(m.child(node, "size")[1])
            net = m.s_str(m.child(node, "net")[1]) if m.child(node, "net") else ""
            vias.append({"at": (float(at[1]), float(at[2])), "size": size, "net": net})
        elif node[0] == "zone":
            net = m.s_str(m.child(node, "net")[1]) if m.child(node, "net") else ""
            lay = m.child(node, "layer")
            layers = [m.s_str(lay[1])] if lay else [m.s_str(x) for x in m.children(node, "layers")[0][1:]]
            pol = m.child(m.child(node, "polygon"), "pts")
            pts = [(float(xy[1]), float(xy[2])) for xy in m.children(pol, "xy")]
            for l in layers:
                zones.append({"net": net, "layer": l, "pts": pts})
    return tracks, vias, zones


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pcb", default=DEFAULT)
    ap.add_argument("--grid", type=float, default=0.1)
    ap.add_argument("--no-refill", action="store_true", help="use the zones as saved (already filled)")
    ap.add_argument("--json", default=os.path.join(os.path.dirname(DEFAULT), "cell18_detour.json"))
    args = ap.parse_args()
    g = args.grid
    if not args.no_refill:
        args.pcb = m.refill_copy(args.pcb)  # kicad-cli fills the zones on the scratch copy
    tracks, vias, zones = load(args.pcb)
    with open(args.pcb, encoding="utf-8") as f:
        root = m.parse_sexpr(f.read())
    fills = []
    for node in root[1:]:
        if isinstance(node, list) and node and node[0] == "zone":
            net = m.s_str(m.child(node, "net")[1]) if m.child(node, "net") else ""
            for fp in m.children(node, "filled_polygon"):
                if m.s_str(m.child(fp, "layer")[1]) != "In2.Cu":
                    continue
                for pts in m.children(fp, "pts"):
                    poly = [(float(xy[1]), float(xy[2])) for xy in m.children(pts, "xy")]
                    fills.append((net, poly))

    nx, ny = int(round(W / g)) + 1, int(round(H / g)) + 1
    blocked = bytearray(nx * ny)

    def idx(i, j):
        return j * nx + i

    def block_seg(a, b, r):
        x0, x1 = min(a[0], b[0]) - r, max(a[0], b[0]) + r
        y0, y1 = min(a[1], b[1]) - r, max(a[1], b[1]) + r
        for j in range(max(0, int(y0 / g)), min(ny, int(y1 / g) + 2)):
            for i in range(max(0, int(x0 / g)), min(nx, int(x1 / g) + 2)):
                if seg_dist(i * g, j * g, a, b) <= r:
                    blocked[idx(i, j)] = 1

    def block_pt(p, r):
        block_seg(p, p, r)

    # port tracks on every layer: the band itself is off limits (plus margin)
    for t in tracks:
        if m.is_port(t["net"]) or t["net"] in BAND_CHIP:
            block_seg(t["a"], t["b"], t["w"] / 2 + CELL_W / 2 + CLR + 0.2)
    # other In2 tracks
    for t in tracks:
        if t["layer"] == "In2.Cu" and t["net"] != "/CELL18":
            block_seg(t["a"], t["b"], t["w"] / 2 + CELL_W / 2 + CLR)
    # vias on any layer (other than CELL18)
    for v in vias:
        if v["net"] != "/CELL18":
            block_pt(v["at"], v["size"] / 2 + CELL_W / 2 + CLR)
    # In2 zones: their outline (the pour's edge) plus the VCOLL range rule, applied as polygon test
    for net, poly in fills:
        if net == "/CELL18" or len(poly) < 3:
            continue
        xs = [p[0] for p in poly]
        ys = [p[1] for p in poly]
        for j in range(max(0, int((min(ys) - VCOLL_CLR) / g)), min(ny, int((max(ys) + VCOLL_CLR) / g) + 2)):
            for i in range(max(0, int((min(xs) - VCOLL_CLR) / g)), min(nx, int((max(xs) + VCOLL_CLR) / g) + 2)):
                x, y = i * g, j * g
                if m.point_in_poly(x, y, poly):
                    blocked[idx(i, j)] = 1
                    continue
                d = min(seg_dist(x, y, poly[k], poly[(k + 1) % len(poly)]) for k in range(len(poly)))
                if d <= VCOLL_CLR:
                    blocked[idx(i, j)] = 1
    # board edge margin and mounting holes
    for j in range(ny):
        for i in range(nx):
            x, y = i * g, j * g
            if x < 0.5 or x > W - 0.5 or y < 0.5 or y > H - 0.5:
                blocked[idx(i, j)] = 1
            for hx, hy in HOLES:
                if math.hypot(x - hx, y - hy) <= HOLE_KEEP:
                    blocked[idx(i, j)] = 1

    # start / goal: CELL18 top via (In2 end) and the stub via above R302
    cell18 = [t for t in tracks if t["net"] == "/CELL18"]
    top = next(v for v in vias if v["net"] == "/CELL18" and v["at"][1] < 20)
    end = next(v for v in vias if v["net"] == "/CELL18" and v["at"][1] > 26)
    sx, sy = top["at"]
    gx, gy = end["at"]
    # clear the start/end vias themselves: unblock their own discs
    for p in (top["at"], end["at"]):
        for j in range(ny):
            for i in range(nx):
                if math.hypot(i * g - p[0], j * g - p[1]) <= 0.6:
                    blocked[idx(i, j)] = 0
    si, sj = int(round(sx / g)), int(round(sy / g))
    gi, gj = int(round(gx / g)), int(round(gy / g))

    # A* on the grid, 8-connected, with a small turn penalty
    def h(i, j):
        return math.hypot(i - gi, j - gj)

    openq = [(h(si, sj), 0.0, si, sj)]
    came = {(si, sj): None}
    cost = {(si, sj): 0.0}
    found = None
    while openq:
        _, c, i, j = heapq.heappop(openq)
        if (i, j) == (gi, gj):
            found = (i, j)
            break
        if c > cost.get((i, j), 1e18):
            continue
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                if di == 0 and dj == 0:
                    continue
                ni, nj = i + di, j + dj
                if not (0 <= ni < nx and 0 <= nj < ny) or blocked[idx(ni, nj)]:
                    continue
                step = math.hypot(di, dj)
                nc = c + step
                if (i, j) in came and came[(i, j)] is not None:
                    pi, pj = came[(i, j)]
                    if (i - pi, j - pj) != (di, dj):
                        nc += 0.05
                if nc < cost.get((ni, nj), 1e18):
                    cost[(ni, nj)] = nc
                    came[(ni, nj)] = (i, j)
                    heapq.heappush(openq, (nc + h(ni, nj), nc, ni, nj))
    if not found:
        print("NO ROUTE on In2 with these clearances")
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump({"found": False}, f)
        return 1
    path = []
    cur = found
    while cur is not None:
        path.append(cur)
        cur = came[cur]
    path.reverse()
    pts = [(i * g, j * g) for i, j in path]

    # line-of-sight simplification: keep a point only when the straight run leaves the blocked area
    def clear(a, b):
        n = int(math.hypot(b[0] - a[0], b[1] - a[1]) / (g / 2)) + 1
        for k in range(n + 1):
            x = a[0] + (b[0] - a[0]) * k / n
            y = a[1] + (b[1] - a[1]) * k / n
            if blocked[idx(int(round(x / g)), int(round(y / g)))]:
                return False
        return True

    simp = [pts[0]]
    k = 0
    while k < len(pts) - 1:
        far = k + 1
        for r in range(len(pts) - 1, k, -1):
            if clear(pts[k], pts[r]):
                far = r
                break
        simp.append(pts[far])
        k = far
    length = sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(simp, simp[1:]))
    out = {"found": True, "waypoints": [(round(x, 3), round(y, 3)) for x, y in simp],
           "length_mm": round(length, 2), "start_via": top["at"], "end_via": end["at"]}
    with open(args.json, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1)
    print(f"route found: {len(simp)} waypoints, {length:.1f} mm on In2")
    for p in out["waypoints"]:
        print(f"  {p}")
    print(f"json: {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
