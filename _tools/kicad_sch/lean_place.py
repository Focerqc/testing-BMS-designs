"""Trial placement for the 18S Lean shrink: the whole board from a few knobs (2026-11-08).

Change the KNOBS below and run again; every run places every part from scratch, so a try is
cheap and nothing depends on the previous one. Close KiCad first.

  "C:\\Program Files\\KiCad\\10.0\\bin\\python.exe" _tools/kicad_sch/lean_place.py [--dry] [--drc] [--pcb FILE]

pcbnew only reads pads and courtyards here; it never saves. The board file is edited as text,
like pcb_move.py does: the copper layer list, the four Edge.Cuts lines, each footprint's (at ...)
line, and the VCOLL zones and vias for Q301 (written unfilled; KiCad fills them, key B). Parts are
placed by courtyard centre, so connectors (whose origin is pin 1) land where you'd expect.
Afterwards it lists courtyard overlaps and parts outside the outline; --drc also runs
kicad-cli DRC and counts the violations by type (unrouted nets are expected at this stage).

Try 4 floorplan (2026-11-11, 70 x 32: the user wants 5 mm off the height so the carrier can hold
connectors above the slaves). Try 3c (70 x 37) is commit 5306098. The connectors are where the
user put them: cell plugs on the top edge, the NTC plug J2 standing on the left edge, the isoSPI
GH plugs top-right just under H3. What changed to lose 5 mm:
  - series resistors R100-R118 are 0402 lying down under the standing 1206 balance row (2 mm),
    tap room 0.5 mm (0.5 mm), and only BELOW = 1.3 mm under U1 instead of 3.4 mm (2.1 mm); the
    fan-in gap above U1 is what is left (printed by the report).
  - U1's bottom pins (S3...C0, GPIO1-4) have to leave through vias under the chip on inner
    layers; only VREG runs along the 1 mm strip under U1 to C303.
  - right of U1, bottom-aligned column in U1's pin order: R402, R401, C304, C305, a gap for
    DRIVE, C303. C301/R301 lie at pin 1 above the isoSPI pairs.
  - Q301 stands right of the column with its pins down and its tab up (the 6 mm under the isoSPI
    termination rows is too low for it lying). C302 stands right of it, R302 lies right of that.
    Its pins run DRIVE, VCOLL, VREG from the left, so VREG (22 mA) comes back under the body and
    through the column gap to C303, and DRIVE (1 mA) has to hop over it on an inner layer.
  - one VCOLL zone on all four layers: round Q301 and under C302/R302, stitched with vias. VCOLL
    ranges from stack minus 35.35 V to stack; the fill follows make_rules.py's range rule.
  - the port A pair has no way past Q301 and port B's termination row on the front: inner layer.
  - NTC filter parts under J2. GPIO1-4 and VREF2 need an inner layer to reach them.
"""
import argparse
import json
import re
import subprocess
import sys
import uuid
from collections import Counter
from pathlib import Path

import pcbnew

sys.path.insert(0, str(Path(__file__).resolve().parent))
from kisch import KICAD_CLI, ROOT  # noqa: E402
from pcb_move import apply_moves  # noqa: E402

PCB = ROOT / "slave-18s-lean" / "adbms1818-slave-18s-lean.kicad_pcb"
if "--pcb" in sys.argv:          # a scratch copy for trials (needed before the board is loaded below)
    PCB = Path(sys.argv[sys.argv.index("--pcb") + 1]).resolve()

# ---------------------------------------------------------------- KNOBS (mm, board coordinates)
W, H = 70.0, 32.0        # board outline, top-left corner at (0, 0); the XR slot is 37 high
EDGE = 0.3               # courtyards stay this far inside the outline
HOLE_INSET = 2.5         # M2 hole centres this far in from each corner
PLUG_X = 5.25            # left courtyard edge of J1 (clear of H4)
J2_XY = (1.05, 5.91)     # top-left courtyard corner of J2, standing on the left edge (user, 2026-11-10)
PITCH = 2.4              # channel pitch along the row (1206 R2 pad 1.75 + 0.2 + 0.25 + 0.2)
ROW_SHIFT = 0.25         # row centre minus plug-pin centre (R100, lying, clears J2)
TAP = 0.5                # plug courtyards -> R2 (outer) row courtyards; the taps also fan out under the plug bodies
ROW_GAP = 0.25           # R2 row courtyards -> R1 (inner) row courtyards
BELOW = 1.3              # U1 courtyard -> bottom edge: one VREG trace; the other bottom pins use vias
U1_X = 36.0              # U1 centre x (rotation stays 270). 42.5 centres its top pins under ch 11-18
                         # (try 3b); 37 was try 3c; 36 lets Q301 stand left of port B's termination row
COL_GAP = 0.6            # U1 courtyard -> supply column: VREF2 and DRIVE run down side by side here
DRIVE_GAP = 0.9          # in the column between C305 and C303: DRIVE passes through to Q301
GAP = 0.3                # between parts packed into a block
ISO_X = 52.82            # left courtyard edge of port B (T601 + J4); port A (T501 + J3) is right of it
ISO_Y = 5.07             # top courtyard edge of the GH plugs J4/J3 (clear of H3)
PARK_X = W + 6           # where parked parts wait
LAYERS = 4               # copper layers: F, In1, In2, B (decided 2026-11-10)
HOLE_KEEP = 2.75         # copper keep-out radius round an M2 hole centre (make_rules.py HOLES)
HV = 0.6                 # VCOLL range vs >30 V neighbours, plus conservative bank rules
VIA = (0.6, 0.3)         # stitching via pad / hole
VIA_PITCH = 1.15         # stitching via pitch
VCOLL_PAD_MARGIN = HV + VIA[0] / 2 + 0.05  # R302 CELL18 pad edge to stitching-via centre
VCOLL_BODY_TOP = 1.50    # first via row below R302's pad top, clears CELL18 lane at y=27.8

# ---------------------------------------------------------------- helpers
mm, nm = pcbnew.ToMM, pcbnew.FromMM
board = pcbnew.LoadBoard(str(PCB))
FP = {f.GetReference(): f for f in board.GetFootprints()}
placed = {}
copper = {"zones": [], "vias": []}      # Q301's VCOLL area, filled in by floorplan()
info = {}                               # measurements for the report


def court(fp):
    fp.BuildCourtyardCaches()
    bb = fp.GetCourtyard(pcbnew.B_CrtYd if fp.GetLayer() == pcbnew.B_Cu else pcbnew.F_CrtYd).BBox()
    return bb if bb.GetWidth() > 0 else fp.GetBoundingBox(False)


def size(ref, rot=None):
    fp = FP[ref]
    if rot is not None:
        fp.SetOrientationDegrees(rot)
    bb = court(fp)
    return mm(bb.GetWidth()), mm(bb.GetHeight())


def put(ref, cx, cy, rot=None):
    """Courtyard centre of REF to (cx, cy); rot in degrees (None keeps it)."""
    fp = FP[ref]
    if rot is not None:
        fp.SetOrientationDegrees(rot)
    bb = court(fp)
    p = fp.GetPosition()
    fp.SetPosition(pcbnew.VECTOR2I(p.x + nm(cx) - bb.GetCenter().x, p.y + nm(cy) - bb.GetCenter().y))
    placed[ref] = fp


def put_anchor(ref, x, y, rot=None):
    fp = FP[ref]
    if rot is not None:
        fp.SetOrientationDegrees(rot)
    fp.SetPosition(pcbnew.VECTOR2I(nm(x), nm(y)))
    placed[ref] = fp


def box(refs):
    """Courtyard bounding box (x0, y0, x1, y1) of placed parts."""
    bbs = [court(FP[r]) for r in refs]
    return (min(mm(b.GetLeft()) for b in bbs), min(mm(b.GetTop()) for b in bbs),
            max(mm(b.GetRight()) for b in bbs), max(mm(b.GetBottom()) for b in bbs))


def pack(refs, x, y, cols, rot=0):
    """Rows of COLS parts, left to right, top-left courtyard corner at (x, y)."""
    for i in range(0, len(refs), cols):
        row = refs[i:i + cols]
        hs = [size(r, rot)[1] for r in row]
        cx = x
        for r in row:
            w, h = size(r, rot)
            put(r, cx + w / 2, y + max(hs) / 2, rot)
            cx += w + GAP
        y += max(hs) + GAP
    return y


def harness_up(ref):
    """Vertical rotation (90 or 270) that puts the CELLn pad on top."""
    fp = FP[ref]
    for rot in (90, 270):
        fp.SetOrientationDegrees(rot)
        ys = {pd.GetNetname(): pd.GetPosition().y for pd in fp.Pads()}
        cell = [y for n, y in ys.items() if re.fullmatch(r"/CELL\d+", n)]
        other = [y for n, y in ys.items() if not re.fullmatch(r"/CELL\d+", n)]
        if cell and other and cell[0] < other[0]:
            return rot
    sys.exit(f"{ref}: no CELL pad")


def chip_down(ref):
    """Transformer rotation (90 or 270) that puts the chip-side pads (1-3) below the line side."""
    fp = FP[ref]
    for rot in (90, 270):
        fp.SetOrientationDegrees(rot)
        y = {pd.GetNumber(): pd.GetPosition().y for pd in fp.Pads()}
        if y["1"] > y["6"]:
            return rot
    sys.exit(f"{ref}: no rotation puts the chip side down")


def pad_box(ref, net):
    """(x0, y0, x1, y1) over REF's pads on NET."""
    bbs = [pd.GetBoundingBox() for pd in FP[ref].Pads() if pd.GetNetname() == net]
    return (min(mm(b.GetLeft()) for b in bbs), min(mm(b.GetTop()) for b in bbs),
            max(mm(b.GetRight()) for b in bbs), max(mm(b.GetBottom()) for b in bbs))


def net_left(ref, net):
    """Horizontal rotation (0 or 180) that puts REF's NET pad on the left."""
    fp = FP[ref]
    for rot in (0, 180):
        fp.SetOrientationDegrees(rot)
        xs = {pd.GetNetname(): pd.GetPosition().x for pd in fp.Pads()}
        if xs[net] == min(xs.values()):
            return rot
    sys.exit(f"{ref}: no pad on {net}")


def net_up(ref, net):
    """Vertical rotation (90 or 270) that puts REF's NET pad(s) on top."""
    fp = FP[ref]
    for rot in (90, 270):
        fp.SetOrientationDegrees(rot)
        ys = [(pd.GetPosition().y, pd.GetNetname() == net) for pd in fp.Pads()]
        low = max(y for y, _ in ys)
        if min(ys)[1] and any(y == low and not on for y, on in ys):
            return rot
    sys.exit(f"{ref}: no rotation puts {net} on top")


def tl(ref, x, y, rot=0):
    """Top-left courtyard corner of REF to (x, y); returns (right, bottom)."""
    w, h = size(ref, rot)
    put(ref, x + w / 2, y + h / 2, rot)
    return x + w, y + h


# ---------------------------------------------------------------- the floorplan
def floorplan():
    # one hole in each corner: H4 top-left, H3 top-right, H1 bottom-left, H2 bottom-right
    for ref, x, y in (("H4", HOLE_INSET, HOLE_INSET), ("H3", W - HOLE_INSET, HOLE_INSET),
                      ("H1", HOLE_INSET, H - HOLE_INSET), ("H2", W - HOLE_INSET, H - HOLE_INSET)):
        put_anchor(ref, x, y)

    # cell plugs on the top edge, left: J1 and J5 keep their 23.5 mm pin-1 spacing
    put_anchor("J1", 0, 0); put_anchor("J5", 23.5, 0)
    x0, y0, _, _ = box(["J1", "J5"])
    jx, jy = PLUG_X - x0, EDGE - y0
    put_anchor("J1", jx, jy); put_anchor("J5", jx + 23.5, jy)
    plug_bottom = box(["J1", "J5"])[3]
    pins_mid = jx + (23.5 + 9 * 2.0) / 2             # middle of C0 ... C18 on the plugs

    # NTC plug J2 standing on the left edge, under H4
    tl("J2", *J2_XY, 90)
    j2x1, j2y1 = box(["J2"])[2:]

    # the 18-channel row: R2 (balance) outer, standing, harness pads up; R1 (10 ohm, 0402) inner,
    # lying, half a pitch right, Cn_F pad left. Sn comes down between two R1 parts. ch 0 at the left
    xc = pins_mid + ROW_SHIFT - 9 * PITCH + PITCH / 4   # R100 (ch 0); the two rows together centred
    h2 = size("R201", harness_up("R201"))[1]
    h1 = size("R101", 0)[1]
    y2 = plug_bottom + TAP + h2 / 2
    y1 = y2 + h2 / 2 + ROW_GAP + h1 / 2
    for n in range(19):
        put(f"R1{n:02d}", xc + n * PITCH, y1, net_left(f"R1{n:02d}", f"/C{n}_F"))
        if n:
            put(f"R2{n:02d}", xc + n * PITCH - PITCH / 2, y2, harness_up(f"R2{n:02d}"))
    row_bottom = y1 + h1 / 2
    # net tie NT1 stands in the corner between J1.1 (C0), J2 and R201, CELL0 pad up
    put("NT1", (j2x1 + box(["R201"])[0]) / 2, plug_bottom + 0.1 + 0.75, harness_up("NT1"))

    # U1 under ch 11-18; ch 0-10 bus down its left side
    u = size("U1", -90)[1]
    put("U1", U1_X, H - BELOW - u / 2, -90)
    ux0, uy0, ux1, uy1 = box(["U1"])
    info["fan"] = uy0 - row_bottom

    # isoSPI ports, top-right: GH plug, transformer under it with the chip side down, then the
    # four termination parts standing in a row under the transformer. Port B left, A right.
    # Port B's row starts 1.2 mm in from the transformer's left edge: the port A pair comes down there.
    x = ISO_X
    for port, jg in (("6", "J4"), ("5", "J3")):
        t = f"T{port}01"
        tw, th = size(t, chip_down(t))
        gw, gh = size(jg, 0)                         # rot 0: pins toward the transformer
        put(jg, x + tw / 2, ISO_Y + gh / 2, 0)
        put(t, x + tw / 2, ISO_Y + gh + GAP + th / 2)
        rc = [f"R{port}01", f"R{port}02", f"C{port}01", f"C{port}02"]
        rw = sum(size(r, 90)[0] for r in rc) + GAP * 3
        pack(rc, x + tw - rw, ISO_Y + gh + GAP + th + GAP, 4, 90)
        x += tw + GAP
    rc_bottom = box(["R601", "C602"])[3]

    # right of U1, a bottom-aligned column in its pin order: (isoSPI 64-61 run right above it)
    # ICMP 58, IBIAS 57, VREF1 51, VREF2 50, a gap where DRIVE 49 passes through, VREG 48
    sx = ux1 + COL_GAP
    rot = net_left("C303", "/VREG")
    y = H - EDGE - size("C303", rot)[1]
    tl("C303", sx, y, rot)
    y -= DRIVE_GAP
    for ref, net in (("C305", "/VREF2"), ("C304", "/VREF1"), ("R401", "/IBIAS"), ("R402", "/ICMP")):
        rot = net_left(ref, net)
        y -= size(ref, rot)[1]
        tl(ref, sx, y, rot)
        y -= GAP
    col = ["R402", "R401", "C304", "C305", "C303"]
    sx2 = box(col)[2] + GAP
    # V+ filter right of pin 1 (U1's top-right corner), lying under the ch 12-18 fan-in, which
    # comes in from the right above U1's top edge: C301 at the pin, R301 right of it, VP_F pads left
    r, _ = tl("C301", ux1 + 0.35, uy0 + 0.1, net_left("C301", "/VP_F"))
    tl("R301", r + GAP, uy0 + 0.1, net_left("R301", "/VP_F"))
    info["pairs"] = box(col)[1] - box(["C301"])[3]
    # NTC filter parts under J2, three per row (pull-up, cap per channel; TH701 last)
    pack(["R701", "C701", "R702", "C702", "R703", "C703", "R704", "C704", "TH701"],
         J2_XY[0] + 0.25, j2y1 + 0.8, 3)

    # Q301 right of the column, standing: pins down at the bottom edge, tab up
    rot = net_up("Q301", "/VCOLL")
    qw, qh = size("Q301", rot)
    put("Q301", sx2 + qw / 2, H - EDGE - qh / 2, rot)
    qx1 = box(["Q301"])[2]
    # C302 stands right of Q301 under port B's termination row, VCOLL pad up (at the tab);
    # R302 (2512) lies right of it on the bottom edge, VCOLL pad left
    rot = net_up("C302", "/VCOLL")
    r, _ = tl("C302", qx1 + GAP, rc_bottom + GAP, rot)
    rot = net_left("R302", "/VCOLL")
    tl("R302", r + GAP, H - EDGE - size("R302", rot)[1], rot)
    vcoll_area(rc_bottom)


def vcoll_area(rcb):
    """Reserved VCOLL copper for Q301 (collector = tab): one zone on all four layers, round Q301
    and under C302/R302, stitched with vias. The fill keeps 0.6 mm from DRIVE, VREG, V- and the
    isoSPI nets by the .kicad_dru, so the outline may run over their pads."""
    qx0, qy0, qx1, qy1 = box(["Q301"])
    tab = max((pd.GetBoundingBox() for pd in FP["Q301"].Pads() if pd.GetNetname() == "/VCOLL"),
              key=lambda b: b.GetWidth() * b.GetHeight())
    tab_bottom = mm(tab.GetBottom())
    pins_top = min(pad_box("Q301", n)[1] for n in ("/DRIVE", "/VREG"))
    hx = W - HOLE_INSET - HOLE_KEEP - 0.15           # left of H2's keep-out
    bot = H - 0.5                                    # board-edge clearance (.kicad_pro)
    top = rcb + 0.35                                 # under the termination rows' pads
    r = lambda pts: [(round(x, 2), round(y, 2)) for x, y in pts]
    poly = r([(qx0 + 0.2, qy0 + 0.1), (qx1, qy0 + 0.1), (qx1, top), (hx, top), (hx, bot), (qx0 + 0.2, bot)])
    copper["zones"] = [("VCOLL_Q301", ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"], poly)]
    vias = []
    grid = lambda a, b: [round(a + i * VIA_PITCH, 2) for i in range(int((b - a) / VIA_PITCH + 1e-6) + 1)] if b >= a else []
    for x in grid(qx0 + 0.9, qx1 - 0.6):             # under Q301's body, between tab and pins
        vias += [(x, y) for y in grid(tab_bottom + 0.6, pins_top - 1.95)]   # VREG runs above the pins
    rv, rc = pad_box("R302", "/VCOLL"), pad_box("R302", "/CELL18")
    for x in grid(box(["C302"])[2] + 0.6, hx - 0.4):  # the strip above R302
        vias += [(x, y) for y in grid(top + 0.5, rv[1] - 0.6)]
    for x in grid(rv[2] + 0.6, rc[0] - VCOLL_PAD_MARGIN):  # leave 0.65 mm to CELL18 pad
        vias += [(x, y) for y in grid(rv[1] + VCOLL_BODY_TOP, bot - 0.5)]
    copper["vias"] = vias

# ---------------------------------------------------------------- write + report
def outline(text):
    def fix(m):
        blk = m.group(0)
        if '(layer "Edge.Cuts")' not in blk:
            return blk
        return re.sub(r"\((start|end) ([-\d.]+) ([-\d.]+)\)",
                      lambda q: f"({q.group(1)} {W if float(q.group(2)) > 0 else 0:g} "
                                f"{H if float(q.group(3)) > 0 else 0:g})", blk)
    new, n = re.subn(r"^\t\(gr_line\n.*?^\t\)", fix, text, flags=re.M | re.S)
    return new


def area(pts):
    return abs(sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(pts, pts[1:] + pts[:1]))) / 2


def inside(pt, pts):
    x, y, hit = *pt, False
    for (x0, y0), (x1, y1) in zip(pts, pts[1:] + pts[:1]):
        if (y0 > y) != (y1 > y) and x < x0 + (y - y0) * (x1 - x0) / (y1 - y0):
            hit = not hit
    return hit


def set_layers(text):
    """Make the board LAYERS copper layers (the layer list only; no stack-up block is written)."""
    inner = "".join(f'\t\t({2 + 2 * n} "In{n}.Cu" signal)\n' for n in range(1, LAYERS - 1))
    text = re.sub(r'^\t\t\(\d+ "In\d+\.Cu" signal\)\n', "", text, flags=re.M)
    return text.replace('\t\t(0 "F.Cu" signal)\n', '\t\t(0 "F.Cu" signal)\n' + inner, 1)


def top_level(text, head):
    """(start, end) of each top-level (HEAD ...) block, with its line break."""
    for m in re.finditer(rf"^\t\({head}\n.*?^\t\)\n", text, re.M | re.S):
        yield m.start(), m.end()


def set_copper(text):
    """Replace Q301's VCOLL zones and stitching vias with the ones from vcoll_area()."""
    drop = [(s, e) for s, e in top_level(text, "zone") if '(name "VCOLL_Q301' in text[s:e]]
    for s, e in top_level(text, "via"):
        blk = text[s:e]
        if '(net "/VCOLL")' in blk:              # also removes routing's pin-2 via; run lean_route next
            drop.append((s, e))
    for s, e in sorted(drop, reverse=True):
        text = text[:s] + text[e:]
    uid = lambda *k: uuid.uuid5(uuid.NAMESPACE_URL, "lean_place/" + "/".join(map(str, k)))
    new = []
    for x, y in copper["vias"]:
        new.append(f'\t(via\n\t\t(at {x:g} {y:g})\n\t\t(size {VIA[0]:g})\n\t\t(drill {VIA[1]:g})\n'
                   f'\t\t(layers "F.Cu" "B.Cu")\n\t\t(net "/VCOLL")\n\t\t(uuid "{uid("via", x, y)}")\n\t)\n')
    for name, layers, pts in copper["zones"]:
        lay = (f'(layer "{layers[0]}")' if len(layers) == 1
               else "(layers " + " ".join(f'"{l}"' for l in layers) + ")")
        new.append(f'\t(zone\n\t\t(net "/VCOLL")\n\t\t{lay}\n\t\t(uuid "{uid("zone", name)}")\n'
                   f'\t\t(name "{name}")\n\t\t(hatch edge 0.5)\n\t\t(priority 1)\n'
                   '\t\t(connect_pads yes\n\t\t\t(clearance 0.2)\n\t\t)\n\t\t(min_thickness 0.2)\n'
                   '\t\t(fill\n\t\t\t(thermal_gap 0.5)\n\t\t\t(thermal_bridge_width 0.5)\n'
                   '\t\t\t(island_removal_mode 0)\n\t\t)\n\t\t(polygon\n\t\t\t(pts\n\t\t\t\t'
                   + " ".join(f"(xy {x:g} {y:g})" for x, y in pts) + "\n\t\t\t)\n\t\t)\n\t)\n")
    at = min(i for i in (text.find(k) for k in ("\n\t(zone\n", "\n\t(group ", "\n\t(embedded_fonts ")) if i >= 0) + 1
    return text[:at] + "".join(new) + text[at:]


def report():
    refs = sorted(placed)
    bbs = {r: court(FP[r]) for r in refs}
    parked = {r for r in refs if mm(bbs[r].GetLeft()) >= W}
    over = []
    for i, a in enumerate(refs):
        for b in refs[i + 1:]:
            A, B = bbs[a], bbs[b]
            ox = min(A.GetRight(), B.GetRight()) - max(A.GetLeft(), B.GetLeft())
            oy = min(A.GetBottom(), B.GetBottom()) - max(A.GetTop(), B.GetTop())
            if ox > nm(0.01) and oy > nm(0.01):
                over.append(f"{a}/{b} ({mm(ox):.2f} x {mm(oy):.2f})")
    out = [r for r in refs if r not in parked and (mm(bbs[r].GetLeft()) < -0.01 or mm(bbs[r].GetTop()) < -0.01
                                                   or mm(bbs[r].GetRight()) > W + 0.01 or mm(bbs[r].GetBottom()) > H + 0.01)]
    print(f"board {W:g} x {H:g} mm, {len(refs) - len(parked)} parts on it, {len(parked)} parked: {', '.join(sorted(parked)) or '-'}")
    r1 = box([f"R1{n:02d}" for n in range(19)] + [f"R2{n:02d}" for n in range(1, 19)])
    print(f"row: x {r1[0]:.1f}-{r1[2]:.1f} ({r1[2] - r1[0]:.1f} mm), y {r1[1]:.1f}-{r1[3]:.1f}; U1 courtyard {', '.join(f'{v:.1f}' for v in box(['U1']))}")
    print(f"fan-in gap above U1: {info['fan']:.2f} mm; under U1: {BELOW:g} mm; "
          f"band for the isoSPI pairs right of U1: {info['pairs']:.2f} mm")
    print(f"courtyard overlaps: {len(over)}" + ("".join(f"\n  {o}" for o in over)))
    print(f"outside the outline: {', '.join(out) or 'none'}")
    for name, layers, pts in copper["zones"]:
        print(f"{name}: {area(pts):.0f} mm2 outline on {', '.join(layers)} (the fill is smaller: clearances)")
    polys = [z[2] for z in copper["zones"]]
    stray = [v for v in copper["vias"] if not all(inside(v, p) for p in polys)]
    print(f"VCOLL stitching vias: {len(copper['vias'])}" + (f", NOT inside every zone: {stray}" if stray else ", all inside the zone outline"))
    left = sorted(set(FP) - set(placed))
    if left:
        print(f"NOT PLACED by the floorplan: {', '.join(left)}")
    return over, out


def release():
    """Drop pcbnew's board before writing: on Windows it keeps the file open (Errno 22 on write)."""
    global board
    FP.clear(); placed.clear()
    board = None
    import gc
    gc.collect()


def drc():
    rpt = ROOT / "exports" / "lean_place_drc.json"
    rpt.parent.mkdir(exist_ok=True)
    # --refill-zones fills the VCOLL zones in memory for the check; the board file is not saved
    subprocess.run([KICAD_CLI, "pcb", "drc", "--format", "json", "--severity-all", "--refill-zones",
                    "--output", str(rpt), str(PCB)],
                   capture_output=True, text=True)
    d = json.loads(rpt.read_text(encoding="utf-8"))
    c = Counter(v["type"] for v in d.get("violations", []))
    print(f"DRC ({rpt.relative_to(ROOT).as_posix()}): " + (", ".join(f"{k} {n}" for k, n in c.most_common()) or "clean")
          + f"; unconnected items {len(d.get('unconnected_items', []))}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true", help="report only, don't write the board")
    ap.add_argument("--drc", action="store_true", help="run kicad-cli DRC after writing")
    ap.add_argument("--pcb", help="place this board file instead of the Lean board (a scratch copy)")
    a = ap.parse_args()
    if list(PCB.parent.glob("~*.lck")):
        sys.exit("KiCad has the Lean board open (lock file). Close it first.")
    floorplan()
    report()
    moves = {r: [round(mm(f.GetPosition().x), 3), round(mm(f.GetPosition().y), 3), round(f.GetOrientationDegrees(), 3)]
             for r, f in placed.items()}
    if a.dry:
        print("(dry run, board not written)")
        return
    release()
    with open(PCB, encoding="utf-8", newline="") as f:
        text = f.read()
    text, done = apply_moves(outline(set_layers(text)), moves)
    text = set_copper(text)
    with open(PCB, "w", encoding="utf-8", newline="") as f:
        f.write(text)
    print(f"wrote {PCB.name}: {LAYERS} copper layers, outline {W:g} x {H:g}, {len(done)} footprints, "
          f"{len(copper['zones'])} VCOLL zones, {len(copper['vias'])} vias")
    if a.drc:
        drc()


if __name__ == "__main__":
    main()
