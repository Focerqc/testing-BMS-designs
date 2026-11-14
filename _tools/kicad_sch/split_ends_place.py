"""Split-ends floorplan study (Option 2, scratch only, 2026-11-14): U1 at rotation 180, 90 deg clockwise from today.

Cells 0-2 enter its left side, 3-10 its top, 11-18 its right side. The bottom side carries DRIVE,
VREF, IBIAS/ICMP and isoSPI (61/62 port A, 63/64 port B at the bottom-right). Port A runs left along
the bottom edge to T501 at the left end, port B right to T601 at the right end. Courtyards only.

  "C:\\Program Files\\KiCad\\10.0\\bin\\python.exe" _tools/kicad_sch/split_ends_place.py SCRATCH.kicad_pcb OUT.json --fan 4.9 --band 3.5 [--write]

Scratch copies only: --write drops every track, via and zone. The 2026-11-14 result (70 x 34.2,
0 courtyard overlaps) is the line above. Draw it with split_ends_render.py.
"""
import json
import re
import sys
from pathlib import Path

SCR, OUT = sys.argv[1], sys.argv[2]
if Path(SCR).resolve().parent.name == "slave-18s-lean":
    sys.exit("scratch copies only: copy the board out of slave-18s-lean/ first")
opts = sys.argv[3:]
def opt(name, default, cast=float):
    return cast(opts[opts.index(name) + 1]) if name in opts else default
XU = opt("--xu", 25.0)          # U1 courtyard left
FAN = opt("--fan", 5.5)         # row courtyard bottom (12.32) -> U1 courtyard top
BAND = opt("--band", 3.8)       # U1 courtyard bottom -> board edge
W = opt("--w", 70.0)
WRITE = "--write" in opts

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.argv = [sys.argv[0], "--pcb", SCR]
import lean_place as lp  # noqa: E402

FP, put, tl, size, box, mm, nm = lp.FP, lp.put, lp.tl, lp.size, lp.box, lp.mm, lp.nm
U = 13.49
YU = 12.32 + FAN
H = round(YU + U + BAND, 2)
lp.W, lp.H = W, H


def rot_where(ref, test, rots=(0, 90, 180, 270)):
    fp = FP[ref]
    for r in rots:
        fp.SetOrientationDegrees(r)
        P = {}
        for p in fp.Pads():
            b = p.GetBoundingBox()
            P.setdefault(p.GetNumber(), []).append((mm(p.GetPosition().x), mm(p.GetPosition().y), mm(b.GetWidth()) * mm(b.GetHeight())))
        if test(P):
            return r
    sys.exit(f"{ref}: no rotation fits")


net_right = lambda ref, net: (lp.net_left(ref, net) + 180) % 360
x0 = lambda p: p[0][0]
y0 = lambda p: p[0][1]

for ref in ["J1", "J5", "NT1"] + [f"R1{n:02d}" for n in range(19)] + [f"R2{n:02d}" for n in range(1, 19)]:
    lp.placed[ref] = FP[ref]
lp.put_anchor("H4", 2.5, 2.5)
lp.put_anchor("H3", W - 2.5, 2.5)

# ---------------------------------------------------------------- U1 at 180
put("U1", XU + U / 2, YU + U / 2, 180)
pads = {p.GetNumber(): (mm(p.GetPosition().x), mm(p.GetPosition().y)) for p in FP["U1"].Pads()}
cx, cy = XU + U / 2, YU + U / 2
assert pads["33"][0] < cx - 4 and pads["17"][1] < cy - 4 and pads["1"][0] > cx + 4 and pads["64"][1] > cy + 4

# ---------------------------------------------------------------- left of U1, under the ch 0-2 lanes:
# reference column at the bottom-left corner (VREG 48/55, VREF2 50, VREF1 51, IBIAS 57, ICMP 58)
colx = XU - 0.6 - 3.05
y = cy - 1.0                                   # below C0_F (pin 38), the lowest cell pin on the left side
for ref, net in (("C303", "/VREG"), ("C305", "/VREF2"), ("C304", "/VREF1"), ("R401", "/IBIAS"), ("R402", "/ICMP")):
    r = net_right(ref, net)
    tl(ref, colx, y, r)
    y += size(ref, r)[1] + 0.3
col_bottom = box(["R402"])[3]

# port A: T501 chip side right at the bottom-left, J3 left of it; termination column beside its chip pins
rt = rot_where("T501", lambda P: x0(P["1"]) > x0(P["6"]))
tw, th = size("T501", rt)
rj = rot_where("J3", lambda P: x0(P["1"]) > max(t[0] for t in P["MP"]))
jw, jh = size("J3", rj)
term_x = colx - 0.3 - 3.05
t_right = term_x - 0.3
tl("T501", t_right - tw, H - 0.3 - th, rt)
tb = box(["T501"])
put("J3", tb[0] - 0.3 - jw / 2, (tb[1] + tb[3]) / 2, rj)
y = tb[1] + 0.2
for ref in ("R502", "C502", "R501", "C501"):     # IMA side up (pin 3 is the upper chip pin), CT in the middle
    tl(ref, term_x, y, 0)
    y += size(ref, 0)[1] + 0.3

# regulator above port A: Q301 lying, pins right (VREG top), tab left; R302 standing top-left
rq = rot_where("Q301", lambda P: max(P["2"], key=lambda t: t[2])[0] < x0(P["1"]) and y0(P["3"]) < y0(P["1"]))
qw, qh = size("Q301", rq)
tl("Q301", term_x + 3.05 - qw, YU - 0.65, rq)
qb = box(["Q301"])
# R302 lying left of Q301 (one VCOLL block), CELL18 pad on the left; C302 standing between them
rc = lp.net_up("C302", "/VCOLL"); cw = size("C302", rc)[0]
tl("C302", qb[0] - 0.3 - cw, YU - 0.65, rc)
rr = lp.net_left("R302", "/CELL18")
tl("R302", qb[0] - 0.3 - cw - 0.3 - size("R302", rr)[0], YU - 0.65 + 0.6, rr)

# V+ filter right of U1's bottom-right corner, under the ch 11-18 lanes' ends (pin 1 is the lowest right pin)
ux1 = XU + U
tl("C301", ux1 + 0.3, pads["1"][1] + 0.6, lp.net_left("C301", "/VP_F"))
tl("R301", ux1 + 0.3, box(["C301"])[3] + 0.3, lp.net_left("R301", "/VP_F"))

# ---------------------------------------------------------------- right end
tl("J2", 52.22, 0.3, 90)
lp.pack(["R701", "C701", "R702", "C702", "R703", "C703", "R704", "C704", "TH701"], box(["J2"])[2] + 0.3, 5.3, 3)
rt6 = rot_where("T601", lambda P: x0(P["1"]) < x0(P["6"]))
t6w, t6h = size("T601", rt6)
rj4 = rot_where("J4", lambda P: x0(P["1"]) < min(t[0] for t in P["MP"]))
j4w, j4h = size("J4", rj4)
tl("T601", W - 0.3 - j4w - 0.3 - t6w, H - 0.3 - t6h, rt6)
t6 = box(["T601"])
put("J4", W - 0.3 - j4w / 2, (t6[1] + t6[3]) / 2, rj4)
lp.put_anchor("H2", W - 2.5, box(["J4"])[1] - 0.3 - 2.5)
lp.pack(["R602", "R601", "C601", "C602"], t6[0], t6[1] - 0.3 - 1.95, 4, 90)
lp.put_anchor("H1", opt("--h1x", 46.0), H - 5.2)   # the bottom-left corner is port A's; free area right of the lanes

# ---------------------------------------------------------------- report + dump
refs = sorted(lp.placed)
bbs = {r: lp.court(FP[r]) for r in refs}
over = []
for i, a in enumerate(refs):
    for b in refs[i + 1:]:
        A, B = bbs[a], bbs[b]
        ox = min(A.GetRight(), B.GetRight()) - max(A.GetLeft(), B.GetLeft())
        oy = min(A.GetBottom(), B.GetBottom()) - max(A.GetTop(), B.GetTop())
        if ox > nm(0.01) and oy > nm(0.01):
            over.append(f"{a}/{b} ({mm(ox):.2f} x {mm(oy):.2f})")
out = [r for r in refs if mm(bbs[r].GetLeft()) < -0.01 or mm(bbs[r].GetTop()) < -0.01
       or mm(bbs[r].GetRight()) > W + 0.01 or mm(bbs[r].GetBottom()) > H + 0.01]
print(f"turned: board {W:g} x {H:g} (U1 x {XU}, fan {FAN}, band {BAND}); {len(refs)} placed; not placed: {sorted(set(FP) - set(lp.placed)) or '-'}")
print(f"courtyard overlaps: {len(over)}" + "".join(f"\n  {o}" for o in over))
print(f"outside the outline: {', '.join(out) or 'none'}")
geo = {"W": W, "H": H, "XU": XU, "YU": YU, "U": U, "FAN": FAN, "UG": BAND, "variant": "turn", "parts": {}}
for r in refs:
    fp, b = FP[r], bbs[r]
    geo["parts"][r] = {"rot": fp.GetOrientationDegrees(),
                       "cy": [mm(b.GetLeft()), mm(b.GetTop()), mm(b.GetRight()), mm(b.GetBottom())],
                       "pads": [{"n": p.GetNumber(), "net": p.GetNetname(), "x": mm(p.GetPosition().x), "y": mm(p.GetPosition().y),
                                 "w": mm(p.GetBoundingBox().GetWidth()), "h": mm(p.GetBoundingBox().GetHeight())} for p in fp.Pads()]}
Path(OUT).write_text(json.dumps(geo), encoding="utf-8")
if WRITE:
    moves = {r: [round(mm(f.GetPosition().x), 3), round(mm(f.GetPosition().y), 3), round(f.GetOrientationDegrees(), 3)]
             for r, f in lp.placed.items()}
    lp.release()
    text = Path(SCR).read_text(encoding="utf-8")
    for head in ("segment", "via", "zone", "arc"):
        text = re.sub(rf"^\t\({head}\n.*?^\t\)\n", "", text, flags=re.M | re.S)
    text, done = lp.apply_moves(lp.outline(text), moves)
    Path(SCR).write_text(text, encoding="utf-8", newline="")
    print(f"wrote scratch {Path(SCR).name}: {len(done)} footprints, outline {W:g} x {H:g}")
