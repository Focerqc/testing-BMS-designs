"""Lane count + picture for the split-ends study (split_ends_place.py's JSON).

  python _tools/kicad_sch/split_ends_render.py GEO.json OUT.png [--panel PANEL.png]

Counts lanes per layer at the busiest cuts (as-built pitches from lean_route.py: front 0.45, In1 0.6,
bus 0.48), sketches each net as a lane, checks the sketch for isoSPI crossings and writes OUT.png,
OUT.svg and OUT_numbers.json. Needs PyMuPDF. The lanes are a count, not a route.
"""
import json
import math
import sys

import pymupdf

geo = json.load(open(sys.argv[1], encoding="utf-8"))
OUT = sys.argv[2]
PANEL = sys.argv[sys.argv.index("--panel") + 1] if "--panel" in sys.argv else None
P = geo["parts"]
W, H, XU, YU, U = geo["W"], geo["H"], geo["XU"], geo["YU"], geo["U"]
UX1, CX, CY = XU + U, XU + U / 2, YU + U / 2
ROW = 12.32
F_P, I1_P, I2_P, BUS_P = 0.45, 0.6, 0.45, 0.48
TIP, RING = 0.775, 0.775 + 0.545 + 0.25        # pad centre -> outer tip / -> ring via inside the pad row


def pad(ref, net=None, num=None):
    for p in P[ref]["pads"]:
        if (net and p["net"] == net) or (num and p["n"] == num):
            return p
    raise KeyError(ref, net, num)


cy = lambda r: P[r]["cy"]
upin = {p["n"]: p for p in P["U1"]["pads"]}
pin_of = {}
for n, p in upin.items():
    pin_of.setdefault(p["net"], []).append(n)


def side_of(p):
    x, y = p["x"] - CX, p["y"] - CY
    return "L" if x < -4 else "R" if x > 4 else "T" if y < -4 else "B"


inward = {"L": (1, 0), "R": (-1, 0), "T": (0, 1), "B": (0, -1)}
cells_F = [f"/C{k}_F" for k in range(19)]
cells_S = [f"/S{k}" for k in range(1, 19)]
side = {n: side_of(upin[pin_of[n][0]]) for n in cells_F + cells_S}
side["/CELL18"] = "R"
key = lambda n: 99 if n == "/CELL18" else (float(n.split("C")[1].split("_")[0]) if n.startswith("/C") else float(n[2:]) - 0.5)

row = {}
for k in range(19):
    p = pad(f"R1{k:02d}", f"/C{k}_F"); row[f"/C{k}_F"] = (p["x"], p["y"] + p["h"] / 2)
for k in range(1, 19):
    p = pad(f"R2{k:02d}", f"/S{k}"); row[f"/S{k}"] = (p["x"], ROW + 0.625)
c18 = pad("R118", "/CELL18"); row["/CELL18"] = (c18["x"], c18["y"] + c18["h"] / 2)

# columns: right side (inner = top pin = smallest key), left side (inner = top pin = largest key)
F_nets, I_nets = cells_F + ["/CELL18"], cells_S
col = {}
for nets, pitch in ((F_nets, BUS_P), (I_nets, I1_P)):
    r = sorted([n for n in nets if side[n] == "R"], key=key)
    l = sorted([n for n in nets if side[n] == "L"], key=lambda n: -key(n))
    col.update({n: UX1 + 0.69 + i * pitch for i, n in enumerate(r)})
    col.update({n: XU - 0.69 - i * pitch for i, n in enumerate(l)})
ZONE_R = max(v for n, v in col.items() if v > CX) + 0.3
ZONE_L = min(v for n, v in col.items() if v < CX) - 0.3
end_x = lambda n: col[n] if n in col else upin[pin_of[n][0]]["x"]


def river(nets, yb, pitch):
    iv = {n: (row[n][0], end_x(n)) for n in nets}
    xs = sorted({v for a in iv.values() for v in a})
    dens, where, ranks = 0, 0, {}
    for a, b in zip(xs, xs[1:]):
        m = (a + b) / 2
        act = [n for n in nets if min(iv[n]) < m < max(iv[n])]
        order = sorted([n for n in act if iv[n][0] < iv[n][1]], key=key) + \
            sorted([n for n in act if iv[n][0] > iv[n][1]], key=lambda n: -key(n))
        if len(act) > dens:
            dens, where = len(act), m
        for r, n in enumerate(order):
            ranks.setdefault(n, []).append((a, b, yb(m) - r * pitch))
    paths = {}
    for n in nets:
        segs = ranks.get(n, [])
        if iv[n][0] > iv[n][1]:
            segs = [(b, a, y) for a, b, y in reversed(segs)]
        pts = [row[n]]
        for i, (a, b, y) in enumerate(segs):
            if i == 0:
                pts.append((a, y))
            elif abs(pts[-1][1] - y) > 1e-6:
                s = 1 if b > a else -1
                d = min(abs(pts[-1][1] - y), abs(b - a) * 0.8)
                pts += [(a + 0.15 * s, pts[-1][1]), (a + 0.15 * s + d * s, y)]
            pts.append((b, y))
        if not segs:
            pts.append((row[n][0], yb(row[n][0])))
        paths[n] = pts
    return paths, dens, where


inU = lambda x: XU + 0.3 < x < UX1 - 0.3
pF, dF, wF = river(F_nets, lambda x: YU - 1.01, F_P)
pI, dI, wI = river(I_nets, lambda x: YU + 0.99 if inU(x) else YU - 1.25, I1_P)
r301 = pad("R301", "/CELL18")
for paths, lay in ((pF, "F"), (pI, "I")):
    for n, pts in paths.items():
        if n == "/CELL18":
            pts += [(pts[-1][0], r301["y"]), (r301["x"], r301["y"])]
            continue
        p = upin[pin_of[n][0]]; s = side[n]; ix, iy = inward[s]
        d = -TIP if lay == "F" else RING
        tx, ty = p["x"] + ix * d, p["y"] + iy * d
        if s == "T":
            pts.append((p["x"], ty))
        else:
            pts += [(pts[-1][0], p["y"]), (tx, p["y"])]

# In2: GPIO1-4 (ring vias on the left side, up under the top pad row, right to the NTC parts), VREF2, CELL18 -> R302
in2 = {}
lane = ROW + 1.6
ntc = {"/GPIO1": "R701", "/GPIO2": "R702", "/GPIO3": "R703", "/GPIO4": "R704"}
for i, net in enumerate(["/GPIO4", "/GPIO3", "/GPIO2", "/GPIO1"]):
    p = upin[pin_of[net][0]]; q = pad(ntc[net], net)
    vx = p["x"] - 0.2 + 0.45 * i                  # In2 up under the left pad row, left of the S1-S3 ring vias
    y = lane + 0.6 + (3 - i) * I2_P
    in2[net] = [(p["x"] + RING, p["y"]), (vx, p["y"] - 0.4), (vx, y), (q["x"], y), (q["x"], q["y"])]
c = pad("C305", "/VREF2"); q = pad("R701", "/VREF2")
y = lane + 0.6 + 4 * I2_P
in2["/VREF2"] = [(c["x"], c["y"]), (c["x"] - 0.9, c["y"]), (c["x"] - 0.9, y), (q["x"], y), (q["x"], q["y"])]
r302 = pad("R302", "/CELL18")
in2["/CELL18 to R302"] = [(c18["x"], c18["y"]), (c18["x"], lane), (r302["x"], lane), (r302["x"], r302["y"])]

# local bottom-pin stubs: reference column (left corner) to pins 50, 51, 55, 57, 58 under the pad row
locl = {}
band_y = YU + U + 0.1
for i, (ref, net, pn) in enumerate([("R402", "/ICMP", "58"), ("R401", "/IBIAS", "57"), ("C303", "/VREG", "55"),
                                     ("C304", "/VREF1", "51"), ("C305", "/VREF2", "50")]):
    q = pad(ref, net); p = upin[pn]
    y = band_y + (4 - i) * F_P
    locl[net] = [(q["x"], q["y"]), (q["x"] + 0.8, q["y"]), (q["x"] + 0.8, y), (p["x"], y), (p["x"], p["y"] + TIP)]

# isoSPI
iso = {}
t5 = {n: pad("T501", num=n) for n in "123456"}; j3 = {n: pad("J3", num=n) for n in "12"}
t6 = {n: pad("T601", num=n) for n in "123456"}; j4 = {n: pad("J4", num=n) for n in "12"}
p61, p62, p63, p64 = (upin[n] for n in ("61", "62", "63", "64"))
ya_in = max(y for pts in locl.values() for _, y in pts) + 0.125 + 0.2 + 0.125   # IMA under the bias stubs
ya_out = ya_in + 0.5
tr = cy("T501")[2]
iso["IMA"] = [(p61["x"], p61["y"] + TIP), (p61["x"], ya_in), (tr + 0.75, ya_in), (tr + 0.75, t5["3"]["y"]), (t5["3"]["x"], t5["3"]["y"])]
iso["IPA"] = [(p62["x"], p62["y"] + TIP), (p62["x"], ya_out), (tr + 0.25, ya_out), (tr + 0.25, t5["1"]["y"]), (t5["1"]["x"], t5["1"]["y"])]
yb_in, yb_out = H - 1.125, H - 0.625
xr = cy("T601")[0] + 0.35
iso["IMB"] = [(p63["x"], p63["y"] + TIP), (p63["x"], yb_in), (xr - 0.5, yb_in), (xr - 0.5, t6["3"]["y"]), (t6["3"]["x"], t6["3"]["y"])]
iso["IPB"] = [(p64["x"], p64["y"] + TIP), (p64["x"], yb_out), (xr, yb_out), (xr, t6["1"]["y"] + 0.4), (xr - 1.1, t6["1"]["y"] + 0.4), (xr - 1.1, t6["1"]["y"]), (t6["1"]["x"], t6["1"]["y"])]
for port, t, j in (("A", t5, j3), ("B", t6, j4)):
    iso[f"ISO{port}_LP"] = [(t["6"]["x"], t["6"]["y"]), (j["1"]["x"], j["1"]["y"])]
    iso[f"ISO{port}_LN"] = [(t["4"]["x"], t["4"]["y"]), (j["2"]["x"], j["2"]["y"])]

length = lambda pts: sum(math.dist(a, b) for a, b in zip(pts, pts[1:]))


def seg_x(a, b, c, d):
    def o(p, q, r):
        v = (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])
        return 0 if abs(v) < 1e-9 else (1 if v > 0 else -1)
    return o(a, b, c) * o(a, b, d) < 0 and o(c, d, a) * o(c, d, b) < 0


foreign = {}
others = {**{("F", n): p for n, p in pF.items()}, **{("In1", n): p for n, p in pI.items()},
          **{("In2", n): p for n, p in in2.items()}, **{("F", n): p for n, p in locl.items()}}
for iname, ipts in iso.items():
    for (lay, n), op in others.items():
        if any(seg_x(a, b, c_, d_) for a, b in zip(ipts, ipts[1:]) for c_, d_ in zip(op, op[1:])):
            foreign.setdefault(iname, []).append(f"{n} ({lay})")
same = [(a, b) for a in ("IMA", "IPA") for b in ("IMB", "IPB")
        if any(seg_x(p, q, r, s) for p, q in zip(iso[a], iso[a][1:]) for r, s in zip(iso[b], iso[b][1:]))]

# numbers
nR = (sum(1 for n in F_nets if side[n] == "R"), sum(1 for n in I_nets if side[n] == "R"))
nL = (sum(1 for n in F_nets if side[n] == "L"), sum(1 for n in I_nets if side[n] == "L"))
fan_req = max(1.74 + (dF - 1) * F_P, 1.28 + (dI - 1) * I1_P)
band_req = (ya_out + 0.125 + 0.5) - (YU + U)
d = lambda a, b: math.dist((a["x"], a["y"]), (b["x"], b["y"]))
num = {
    "board": f"{W:g} x {H:g}",
    "fan above U1 (busiest vertical cut)": f"F {dF} at x {wF:.1f}, In1 {dI} at x {wI:.1f}, In2 6",
    "fan height needed / placed": f"{fan_req:.2f} / {geo['FAN']}",
    "right of U1 (ch 11-18 + CELL18)": f"F {nR[0]}, In1 {nR[1]}: zone x {UX1:.1f}-{ZONE_R:.1f} ({ZONE_R - UX1:.1f} mm)",
    "left of U1 (ch 0-2)": f"F {nL[0]}, In1 {nL[1]}: zone x {ZONE_L:.1f}-{XU:.1f} ({XU - ZONE_L:.1f} mm)",
    "under U1": f"5 bias/reference stubs, then port A (2) going left; port B (2) going right; band needed {band_req:.2f} / placed {geo['UG']}",
    "height needed = 12.32 + fan + 13.49 + band": f"{ROW + fan_req + U + band_req:.1f}",
    "T501 -> J3 / T601 -> J4 line pads": f"{min(d(t5['6'], j3['1']), d(t5['4'], j3['2'])):.1f} / {min(d(t6['6'], j4['1']), d(t6['4'], j4['2'])):.1f} mm",
    "U1 61/62 -> T501 chip pads (straight)": f"{d(p61, t5['3']):.1f} / {d(p62, t5['1']):.1f} mm",
    "U1 63/64 -> T601 chip pads (straight)": f"{d(p63, t6['3']):.1f} / {d(p64, t6['1']):.1f} mm",
    "track IMA / IPA / IMB / IPB": " / ".join(f"{length(iso[k]):.1f}" for k in ("IMA", "IPA", "IMB", "IPB")) + " mm",
    "foreign crossings of isoSPI (sketch)": foreign or 0,
    "port A x port B crossings": same or 0,
}
for k, v in num.items():
    print(f"{k}: {v}")
json.dump(num, open(OUT.replace(".png", "_numbers.json"), "w"), indent=1, default=str)

# ---------------------------------------------------------------- SVG
def svg(S, M, TOP, legend):
    X = lambda x: M + x * S
    Y = lambda y: TOP + y * S
    svgW = max(X(W) + M, 1180) if legend else X(W) + M
    svgH = Y(max(H, 32)) + (130 if legend else M)
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{svgW:.0f}" height="{svgH:.0f}" font-family="Arial">',
         f'<rect x="0" y="0" width="{svgW:.0f}" height="{svgH:.0f}" fill="#14161a"/>']
    if legend:
        o.append(f'<text x="{M}" y="24" fill="#fff" font-size="17" font-weight="bold">U1 turned 90° clockwise from today: {W:g} × {H:.1f} mm (scratch placement, courtyards and lanes to scale)</text>')
        o.append(f'<text x="{M}" y="46" fill="#bbb" font-size="12.5">Cells 0–2 enter U1 from the left, 3–10 from the top, 11–18 from the right. Port A (orange) goes left along the bottom, port B (magenta) right. '
                 f'Gold = front, green = In1, blue = In2. Dashed red = today\'s 70 × 32.</text>')
    o.append(f'<rect x="{X(0)}" y="{Y(0)}" width="{W * S}" height="{H * S}" fill="#1e3a2a" stroke="#ccc" stroke-width="1.5"/>')
    o.append(f'<rect x="{X(0)}" y="{Y(0)}" width="{70 * S}" height="{32 * S}" fill="none" stroke="#ff4040" stroke-width="1.5" stroke-dasharray="7,5"/>')
    if legend:
        o.append(f'<text x="{X(70) + 6}" y="{Y(32) + 4}" fill="#ff6060" font-size="12">← 70 × 32 today</text>')
    colr = {"isoA": "#ff8c1a", "isoB": "#e64ce6", "chip": "#29b6f6", "reg": "#43d16b", "vplus": "#ffd23f",
            "ntc": "#7f8cff", "hole": "#888", "cell": "#8a8a8a"}
    def grp(r):
        return ("isoA" if r in ("T501", "J3", "R501", "R502", "C501", "C502") else
                "isoB" if r in ("T601", "J4", "R601", "R602", "C601", "C602") else
                "chip" if r == "U1" else
                "reg" if r in ("Q301", "R302", "C302", "C303", "C304", "C305", "R401", "R402") else
                "vplus" if r in ("C301", "R301") else
                "ntc" if r.startswith(("R70", "C70", "TH7", "J2")) else
                "hole" if r.startswith("H") else "cell")
    for r, v in P.items():
        x0, y0, x1, y1 = v["cy"]
        if grp(r) == "hole":
            hx, hy = (x0 + x1) / 2, (y0 + y1) / 2
            o.append(f'<circle cx="{X(hx)}" cy="{Y(hy)}" r="{2.75 * S}" fill="none" stroke="#666" stroke-dasharray="3,3"/>')
            o.append(f'<circle cx="{X(hx)}" cy="{Y(hy)}" r="{1.1 * S}" fill="#0b0b0b" stroke="#999"/>')
            continue
        for p in v["pads"]:
            o.append(f'<rect x="{X(p["x"] - p["w"] / 2):.1f}" y="{Y(p["y"] - p["h"] / 2):.1f}" width="{p["w"] * S:.1f}" height="{p["h"] * S:.1f}" fill="#6b5a3a" opacity="0.8"/>')
        o.append(f'<rect x="{X(x0):.1f}" y="{Y(y0):.1f}" width="{(x1 - x0) * S:.1f}" height="{(y1 - y0) * S:.1f}" fill="none" stroke="{colr[grp(r)]}" stroke-width="{2.2 if grp(r) != "cell" else 0.8}"/>')
    if legend:
        for r, t in {"U1": "U1 (turned)", "T501": "T501 (A)", "J3": "J3", "T601": "T601 (B)", "J4": "J4",
                     "Q301": "Q301", "R302": "R302", "J2": "J2 NTC"}.items():
            x0, y0, x1, y1 = P[r]["cy"]
            o.append(f'<text x="{X((x0 + x1) / 2)}" y="{Y((y0 + y1) / 2) + 4}" fill="{colr[grp(r)]}" font-size="12" font-weight="bold" text-anchor="middle">{t}</text>')

    def poly(pts, color, w, dash=None, op=0.95):
        s = " ".join(f"{X(x):.1f},{Y(y):.1f}" for x, y in pts)
        da = f' stroke-dasharray="{dash}"' if dash else ""
        o.append(f'<polyline points="{s}" fill="none" stroke="{color}" stroke-width="{w}" opacity="{op}"{da} stroke-linejoin="round"/>')

    for pts in pI.values():
        poly(pts, "#3cb371", 0.3 * S * 0.6, None, 0.75)
    for n, pts in pF.items():
        poly(pts, "#d4a017" if n != "/CELL18" else "#b5ff5c", 0.25 * S * 0.8)
    for pts in locl.values():
        poly(pts, "#d4a017", 0.25 * S * 0.8)
    for n, pts in in2.items():
        poly(pts, "#4f8fe0" if "CELL18" not in n else "#b5ff5c", 0.25 * S * 0.8, "5,3" if "CELL18" in n else None)
    for n, pts in iso.items():
        poly(pts, "#ff8c1a" if ("A" in n[-1:] or "ISOA" in n) else "#e64ce6", 0.3 * S, None, 1.0)
    if legend:
        def cut(x0_, y0_, x1_, y1_, text, tx, ty):
            o.append(f'<line x1="{X(x0_)}" y1="{Y(y0_)}" x2="{X(x1_)}" y2="{Y(y1_)}" stroke="#fff" stroke-width="1.6" stroke-dasharray="2,3"/>')
            o.append(f'<text x="{X(tx)}" y="{Y(ty)}" fill="#fff" font-size="11.5">{text}</text>')
        cut(wF, ROW, wF, YU, f"fan: {dF} F + {dI} In1 + 6 In2", wF + 0.4, ROW + 1.3)
        cut(UX1, CY, ZONE_R, CY, f"right: {nR[0]} F + {nR[1]} In1", ZONE_R + 0.4, CY + 0.3)
        cut(ZONE_L, CY - 2.5, XU, CY - 2.5, f"left: {nL[0]} F + {nL[1]} In1", ZONE_L - 0.2, CY - 3.0)
        ly = Y(max(H, 32)) + 22
        lines = [f"Height needed: {num['height needed = 12.32 + fan + 13.49 + band']} mm (row bottom 12.32 + fan {fan_req:.1f} + U1 13.49 + under-U1 band {band_req:.1f}). Carrier slot 37 mm.",
                 f"Tracks: IMA {length(iso['IMA']):.0f}, IPA {length(iso['IPA']):.0f}, IMB {length(iso['IMB']):.0f}, IPB {length(iso['IPB']):.0f} mm. "
                 f"Foreign crossings of isoSPI in this sketch: {0 if not foreign else sum(map(len, foreign.values()))}; port A × port B: {len(same)}.",
                 f"Transformer–plug {num['T501 -> J3 / T601 -> J4 line pads']} (limit 20 mm). Holes H1/H2 moved off the corners the ports use.",
                 "No routing beyond lanes; DRIVE (Q301 base) and the CT/termination stubs are local hops, not drawn."]
        for i, t in enumerate(lines):
            o.append(f'<text x="{M}" y="{ly + i * 19}" fill="#ddd" font-size="12.5">{t}</text>')
    o.append("</svg>")
    return "\n".join(o)


s = svg(15.0, 16, 74, True)
open(OUT.replace(".png", ".svg"), "w", encoding="utf-8").write(s)
pymupdf.open(stream=s.encode(), filetype="svg")[0].get_pixmap(dpi=110).save(OUT)
if PANEL:   # board only, exactly 16 px/mm for the reference chart (pymupdf renders SVG px at 72 dpi)
    s = svg(16.0, 0, 0, False)
    pymupdf.open(stream=s.encode(), filetype="svg")[0].get_pixmap(dpi=72).save(PANEL)
print("wrote", OUT)
