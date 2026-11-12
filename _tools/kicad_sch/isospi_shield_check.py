"""Check that every isoSPI foreign crossing is shielded by filled V- copper.

Read-only for the real board. It copies the Lean board (and its project files)
into exports/isospi_check/, lets kicad-cli refill the zones on that copy, then:

1. Finds every centreline crossing of an isoSPI port track (ISOA_* or ISOB_*)
   with a foreign track on another layer. Excluded: same port, and V-.
2. For each crossing, samples the whole projected overlap of the two track
   bodies (not just the centre point).
3. Requires every sample to lie inside filled V- copper on each layer strictly
   between the two tracks' layers. A crossing on adjacent layers has no layer
   between them, so it cannot be shielded and is always reported uncovered.

Exit 0 = every crossing covered. Exit 1 = at least one uncovered.
Usage: python isospi_shield_check.py [--pcb FILE] [--step 0.02] [--json OUT]
"""

import argparse
import json
import math
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
DEFAULT_PCB = os.path.join(REPO, "slave-18s-lean", "adbms1818-slave-18s-lean.kicad_pcb")
KICAD_CLI = r"C:\Program Files\KiCad\10.0\bin\kicad-cli.exe"
SCRATCH = os.path.join(REPO, "exports", "isospi_check")
STACK = {"F.Cu": 0, "In1.Cu": 1, "In2.Cu": 2, "B.Cu": 3}
SHIELD_NET = "/V-"


# ---------- minimal s-expression parser -------------------------------------
def parse_sexpr(text):
    tokens = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c in " \t\r\n":
            i += 1
        elif c in "()":
            tokens.append(c)
            i += 1
        elif c == '"':
            j = i + 1
            buf = []
            while text[j] != '"':
                if text[j] == "\\":
                    j += 1
                buf.append(text[j])
                j += 1
            tokens.append(("str", "".join(buf)))
            i = j + 1
        else:
            j = i
            while j < n and text[j] not in " \t\r\n()":
                j += 1
            tokens.append(text[i:j])
            i = j
    stack = [[]]
    for t in tokens:
        if t == "(":
            stack.append([])
        elif t == ")":
            done = stack.pop()
            stack[-1].append(done)
        else:
            stack[-1].append(t)
    return stack[0][0]


def s_str(x):
    return x[1] if isinstance(x, tuple) else x


def children(node, name):
    return [c for c in node if isinstance(c, list) and c and c[0] == name]


def child(node, name):
    r = children(node, name)
    return r[0] if r else None


# ---------- geometry ---------------------------------------------------------
def seg_point_dist(px, py, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    if L2 == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L2))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def seg_intersect(a, b):
    (x1, y1), (x2, y2), (x3, y3), (x4, y4) = a[0], a[1], b[0], b[1]
    d = (x2 - x1) * (y4 - y3) - (y2 - y1) * (x4 - x3)
    if abs(d) < 1e-12:
        return False
    t = ((x3 - x1) * (y4 - y3) - (y3 - y1) * (x4 - x3)) / d
    u = ((x3 - x1) * (y2 - y1) - (y3 - y1) * (x2 - x1)) / d
    return -1e-9 <= t <= 1 + 1e-9 and -1e-9 <= u <= 1 + 1e-9


def in_track(px, py, tr):
    return seg_point_dist(px, py, tr["a"][0], tr["a"][1], tr["b"][0], tr["b"][1]) <= tr["w"] / 2


def point_in_poly(px, py, poly):
    inside = False
    n = len(poly)
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > py) != (yj > py) and px < (xj - xi) * (py - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


# ---------- board extraction -------------------------------------------------
def load_board(path):
    with open(path, encoding="utf-8") as f:
        root = parse_sexpr(f.read())
    tracks, zones = [], []
    for node in root[1:]:
        if not isinstance(node, list) or not node:
            continue
        if node[0] == "segment":
            st = child(node, "start")
            en = child(node, "end")
            net = s_str(child(node, "net")[1]) if child(node, "net") else ""
            tracks.append({
                "a": (float(st[1]), float(st[2])),
                "b": (float(en[1]), float(en[2])),
                "w": float(child(node, "width")[1]),
                "layer": s_str(child(node, "layer")[1]),
                "net": net,
            })
        elif node[0] == "zone":
            if child(node, "net_name"):
                net = s_str(child(node, "net_name")[1])
            elif child(node, "net"):
                net = s_str(child(node, "net")[1])
            else:
                net = ""
            lay = child(node, "layer")
            layers = children(node, "layers")
            if lay:
                zl = [s_str(lay[1])]
            else:
                zl = [s_str(x) for x in layers[0][1:]] if layers else []
            for layer in zl:
                zones.append({"net": net, "layer": layer, "node": node})
    return tracks, zones


def filled_polygons(zones):
    """{(net, layer): [polygon, ...]} from the filled_polygon blocks."""
    out = {}
    done = set()
    for z in zones:
        if id(z["node"]) in done:
            continue
        done.add(id(z["node"]))
        for fp in children(z["node"], "filled_polygon"):
            layer = s_str(child(fp, "layer")[1])
            for pts in children(fp, "pts"):
                poly = [(float(xy[1]), float(xy[2])) for xy in children(pts, "xy")]
                out.setdefault((z["net"], layer), []).append(poly)
    return out


def refill_copy(src):
    os.makedirs(SCRATCH, exist_ok=True)
    base = os.path.splitext(os.path.basename(src))[0]
    src_dir = os.path.dirname(src)
    for f in os.listdir(SCRATCH):
        p = os.path.join(SCRATCH, f)
        if os.path.isfile(p):
            os.remove(p)
    for ext in (".kicad_pcb", ".kicad_pro", ".kicad_dru"):
        s = os.path.join(src_dir, base + ext)
        if os.path.exists(s):
            shutil.copy(s, os.path.join(SCRATCH, base + ext))
    pcb = os.path.join(SCRATCH, base + ".kicad_pcb")
    rpt = os.path.join(SCRATCH, "drc_refill.json")
    subprocess.run([KICAD_CLI, "pcb", "drc", "--refill-zones", "--save-board",
                    "--format", "json", "-o", rpt, pcb],
                   check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return pcb


# ---------- the check --------------------------------------------------------
def is_port(net):
    return net.startswith("/ISOA_") or net.startswith("/ISOB_")


def port_of(net):
    return net[1:5] if is_port(net) else None  # "ISOA" / "ISOB"


def find_crossings(tracks):
    ports = [t for t in tracks if is_port(t["net"])]
    out = []
    for p in ports:
        for q in tracks:
            if q["layer"] == p["layer"] or q["net"] == p["net"]:
                continue
            if q["net"] == SHIELD_NET or q["net"] == "":
                continue
            if is_port(q["net"]) and port_of(q["net"]) == port_of(p["net"]):
                continue
            if seg_intersect((p["a"], p["b"]), (q["a"], q["b"])):
                out.append((p, q))
    return out


def overlap_samples(p, q, step):
    xs = [p["a"][0], p["b"][0], q["a"][0], q["b"][0]]
    ys = [p["a"][1], p["b"][1], q["a"][1], q["b"][1]]
    m = max(p["w"], q["w"]) / 2
    x0, x1 = max(min(xs), min(xs)) - m, max(xs) + m
    y0, y1 = min(ys) - m, max(ys) + m
    samples = []
    nx = int((x1 - x0) / step) + 1
    ny = int((y1 - y0) / step) + 1
    for i in range(nx):
        x = x0 + i * step
        for j in range(ny):
            y = y0 + j * step
            if in_track(x, y, p) and in_track(x, y, q):
                samples.append((x, y))
    return samples


def covered_on_layer(samples, polys):
    """Even-odd coverage of each sample by the shield polygons on one layer."""
    bad = []
    for (x, y) in samples:
        cnt = 0
        for poly in polys:
            xs = [v[0] for v in poly]
            ys = [v[1] for v in poly]
            if x < min(xs) or x > max(xs) or y < min(ys) or y > max(ys):
                continue
            if point_in_poly(x, y, poly):
                cnt += 1
        if cnt % 2 == 0:
            bad.append((x, y))
    return bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pcb", default=DEFAULT_PCB)
    ap.add_argument("--step", type=float, default=0.02)
    ap.add_argument("--json", default=os.path.join(SCRATCH, "isospi_shield_check.json"))
    ap.add_argument("--no-refill", action="store_true",
                    help="use the board as it is (zones must already be filled)")
    args = ap.parse_args()

    pcb = args.pcb if args.no_refill else refill_copy(args.pcb)
    tracks, zones = load_board(pcb)
    fills = filled_polygons(zones)
    crossings = find_crossings(tracks)

    results = []
    for p, q in crossings:
        layers = sorted([p["layer"], q["layer"]], key=lambda l: STACK[l])
        between = [l for l in STACK if STACK[layers[0]] < STACK[l] < STACK[layers[1]]]
        samples = overlap_samples(p, q, args.step)
        uncovered = {}
        for l in between:
            bad = covered_on_layer(samples, fills.get((SHIELD_NET, l), []))
            uncovered[l] = len(bad)
        if not between:
            status = "uncovered: adjacent layers, no layer between"
        elif not samples:
            status = "no overlap samples"
        elif any(uncovered.values()):
            status = "uncovered"
        else:
            status = "covered"
        kind = "port/port" if is_port(q["net"]) else "port/foreign"
        results.append({
            "port_net": p["net"], "port_layer": p["layer"],
            "other_net": q["net"], "other_layer": q["layer"],
            "kind": kind,
            "at": [round((p["a"][0] + p["b"][0] + q["a"][0] + q["b"][0]) / 4, 3),
                   round((p["a"][1] + p["b"][1] + q["a"][1] + q["b"][1]) / 4, 3)],
            "overlap_samples": len(samples),
            "uncovered_samples_by_layer": uncovered,
            "status": status,
        })

    # de-duplicate pairs that were found from both sides (port and foreign both port)
    seen, unique = set(), []
    for r in results:
        key = tuple(sorted([(r["port_net"], r["port_layer"]), (r["other_net"], r["other_layer"])]))
        key = key + (tuple(r["at"]),)
        if key in seen:
            continue
        seen.add(key)
        unique.append(r)
    results = unique

    counts = {"total": len(results), "covered": 0, "uncovered": 0}
    for r in results:
        if r["status"] == "covered":
            counts["covered"] += 1
        else:
            counts["uncovered"] += 1
    counts["by_kind"] = {}
    for r in results:
        counts["by_kind"].setdefault(r["kind"], {"total": 0, "uncovered": 0})
        counts["by_kind"][r["kind"]]["total"] += 1
        if r["status"] != "covered":
            counts["by_kind"][r["kind"]]["uncovered"] += 1

    os.makedirs(os.path.dirname(args.json), exist_ok=True)
    with open(args.json, "w", encoding="utf-8") as f:
        json.dump({"board": args.pcb, "counts": counts, "crossings": results}, f, indent=2)

    print(f"board: {args.pcb}")
    print(f"crossings: {counts['total']}  covered: {counts['covered']}  uncovered: {counts['uncovered']}")
    for k, v in counts["by_kind"].items():
        print(f"  {k}: {v['total']} total, {v['uncovered']} uncovered")
    for r in results:
        if r["status"] != "covered":
            print(f"  UNCOVERED {r['port_net']}@{r['port_layer']} x {r['other_net']}@{r['other_layer']}"
                  f" at {r['at']}: {r['status']} {r['uncovered_samples_by_layer']}")
    print(f"report: {args.json}")
    return 0 if counts["uncovered"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
