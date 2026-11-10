"""Trial placement for the 18S Lean shrink: the whole board from a few knobs (2026-11-08).

Change the KNOBS below and run again; every run places every part from scratch, so a try is
cheap and nothing depends on the previous one. Close KiCad first.

  "C:\\Program Files\\KiCad\\10.0\\bin\\python.exe" _tools/kicad_sch/lean_place.py [--dry] [--drc]

pcbnew only reads pads and courtyards here; it never saves. The board file is edited as text,
like pcb_move.py does: the four Edge.Cuts lines and each footprint's (at ...) line. Parts are
placed by courtyard centre, so connectors (whose origin is pin 1) land where you'd expect.
Afterwards it lists courtyard overlaps and parts outside the outline; --drc also runs
kicad-cli DRC and counts the violations by type (unrouted nets are expected at this stage).
"""
import argparse
import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pcbnew

sys.path.insert(0, str(Path(__file__).resolve().parent))
from kisch import KICAD_CLI, ROOT  # noqa: E402
from pcb_move import apply_moves  # noqa: E402

PCB = ROOT / "slave-18s-lean" / "adbms1818-slave-18s-lean.kicad_pcb"

# ---------------------------------------------------------------- KNOBS (mm, board coordinates)
W, H = 70.0, 50.0        # board outline, top-left corner at (0, 0)
HOLE_INSET = 3.5         # M3 hole centres this far in from each corner
PLUG_Y = 5.0             # J1/J5 pin row; the pair is centred left-right on the top edge
PITCH = 3.3              # channel pitch along the row (2010 R2: 3.3 is the least)
ROW_SHIFT = -2.0         # row centre minus board centre; negative leaves room for J2 on the right
TAP = 5.0                # plug courtyards -> R2 (outer) row courtyards: room for the tap traces
ROW_GAP = 0.25           # R2 row courtyards -> R1 (inner) row courtyards
FAN = 6.0                # R1 row courtyards -> U1 courtyard: fan-in of ch 11-18 to U1's top pins
U1_X = 42.0              # U1 centre x (rotation stays 270: cell pins top and left)
GAP = 0.3                # between parts packed into a block
ISO_B = "right of U1"    # isoSPI port B (OUT: T601, J4, J7): "right of U1", (x, y) top-left, or None
ISO_A = "under port B"   # isoSPI port A (IN: T501, J3, J6): "under port B", (x, y), or None = parked
ISO_PH = False           # only while J6/J7 are still on the board: False parks them (make_lean.py drops them)
ISO_Y = 1.0              # R1 row courtyards -> port B block
ISO_GAP = 0.3            # U1 -> R/C column -> transformer -> GH plug, and port B -> port A
PARK_X = W + 6           # where parked parts wait

# ---------------------------------------------------------------- helpers
mm, nm = pcbnew.ToMM, pcbnew.FromMM
board = pcbnew.LoadBoard(str(PCB))
FP = {f.GetReference(): f for f in board.GetFootprints()}
placed = {}


def court(fp):
    fp.BuildCourtyardCaches()
    bb = fp.GetCourtyard(pcbnew.F_CrtYd).BBox()
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


# ---------------------------------------------------------------- the floorplan
def floorplan():
    # holes in the corners: H4 top-left, H3 top-right, H1 bottom-left, H2 bottom-right
    for ref, x, y in (("H4", HOLE_INSET, HOLE_INSET), ("H3", W - HOLE_INSET, HOLE_INSET),
                      ("H1", HOLE_INSET, H - HOLE_INSET), ("H2", W - HOLE_INSET, H - HOLE_INSET)):
        put_anchor(ref, x, y)

    # cell plugs: J1 and J5 keep their 23.5 mm pin-1 spacing, the pair centred on the top edge;
    # NT1 stays 3.8 mm left of J1.1 (C0)
    put_anchor("J1", 0, PLUG_Y); put_anchor("J5", 23.5, PLUG_Y)
    x0, _, x1, _ = box(["J1", "J5"])
    dx = W / 2 - (x0 + x1) / 2
    put_anchor("J1", dx, PLUG_Y); put_anchor("J5", dx + 23.5, PLUG_Y)
    put_anchor("NT1", dx - 3.8, PLUG_Y, 180)
    plug_bottom = box(["J1", "J5"])[3]

    # NTC plug J2: vertical on the right edge, under H3
    w, h = size("J2", 90)
    put("J2", W - 0.3 - w / 2, HOLE_INSET + 3.8 + h / 2, 90)

    # the 18-channel row: R2 (balance) outer, R1 (10 ohm) inner and half a pitch right,
    # ch 0 at the left, harness pads up
    xc = W / 2 + ROW_SHIFT - 9 * PITCH            # R100 (ch 0)
    h2 = size("R201", harness_up("R201"))[1]
    h1 = size("R101", harness_up("R101"))[1]
    y2 = plug_bottom + TAP + h2 / 2
    y1 = y2 + h2 / 2 + ROW_GAP + h1 / 2
    for n in range(19):
        put(f"R1{n:02d}", xc + n * PITCH, y1, harness_up(f"R1{n:02d}"))
        if n:
            put(f"R2{n:02d}", xc + n * PITCH - PITCH / 2, y2, harness_up(f"R2{n:02d}"))
    row_bottom = y1 + h1 / 2

    # U1 under the row; ch 0-10 bus down its left side
    u = size("U1", -90)[1]
    put("U1", U1_X, row_bottom + FAN + u / 2, -90)
    ux0, _, ux1, uy1 = box(["U1"])

    # under U1: reference caps, isoSPI bias, NTC filter (VREG, VREF1/2, IBIAS and GPIO1-3 are on
    # its bottom side). The area left of U1 and between the row and U1 is kept for the ch 0-10 bus.
    pack(["C303", "C304", "C305", "R401", "R402", "R701", "R702", "R703", "R704", "TH701",
          "C701", "C702", "C703", "C704"], ux0, uy1 + 0.5, 8)

    # bottom-left, below the bus: test loops, then the supply
    left = HOLE_INSET * 2 + 0.9          # Q301's pads clear H1's 2.9 mm copper keep-out
    pack([f"TP{i}" for i in range(1, 11)], 1.0, 36.0, 5)
    q_w, q_h = size("Q301", 0)
    put("Q301", left + q_w / 2, H - 0.5 - q_h / 2, 0)
    qx1 = box(["Q301"])[2]
    pack(["R302", "C302", "R301", "C301"], qx1 + 0.5, H - 0.5 - q_h, 2)
    pack(["TP11", "TP12", "TP13", "TP14"], box(["C301"])[2] + 0.5, H - 0.5 - q_h, 2)

    # isoSPI ports (U1's isoSPI pins are on its right side, port B's above port A's). Each port is
    # one strip, left to right: termination R/C column, transformer (chip side left), GH plug.
    # The PH alternate goes under the GH plug if ISO_PH, else it is parked. None = port parked.
    spots = {"6": ISO_B, "5": ISO_A}
    bottom = None
    for port, park_y in (("6", 2.0), ("5", 22.0)):
        spot = spots[port]
        if spot == "right of U1":
            spot = (ux1 + ISO_GAP, row_bottom + ISO_Y)
        elif spot == "under port B":
            spot = (ux1 + ISO_GAP, bottom + ISO_GAP)
        bottom = port_block(port, *(spot or (PARK_X, park_y)), parked=spot is None)


def port_block(port, x, y, parked=False):
    """Places one port, top-left courtyard corner at (x, y); returns the strip's bottom y."""
    t, jg, jp = f"T{port}01", ("J4" if port == "6" else "J3"), ("J7" if port == "6" else "J6")
    rc = [f"R{port}01", f"R{port}02", f"C{port}01", f"C{port}02"]
    pack(rc, x, y, 1)
    tx = box(rc)[2] + ISO_GAP
    tw, th = size(t, 0)
    put(t, tx + tw / 2, y + th / 2, 0)
    gw, gh = size(jg, -90)
    gx = tx + tw + ISO_GAP
    put(jg, gx + gw / 2, y + gh / 2, -90)
    if jp not in FP:                     # J6/J7 are gone from Lean since 2026-11-09
        return box(rc + [t, jg])[3]
    pw, ph = size(jp, 0)
    if ISO_PH or parked:
        put(jp, gx + pw / 2, y + gh + GAP + ph / 2, 0)
    else:
        put(jp, PARK_X + pw / 2, 2.0 + (0 if port == "6" else ph + 1) + ph / 2, 0)
    return max(box(rc + [t, jg])[3], box([jp])[3] if ISO_PH else 0)


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
    print(f"courtyard overlaps: {len(over)}" + ("".join(f"\n  {o}" for o in over)))
    print(f"outside the outline: {', '.join(out) or 'none'}")
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
    subprocess.run([KICAD_CLI, "pcb", "drc", "--format", "json", "--severity-all", "--output", str(rpt), str(PCB)],
                   capture_output=True, text=True)
    d = json.loads(rpt.read_text(encoding="utf-8"))
    c = Counter(v["type"] for v in d.get("violations", []))
    print(f"DRC ({rpt.relative_to(ROOT)}): " + (", ".join(f"{k} {n}" for k, n in c.most_common()) or "clean")
          + f"; unconnected items {len(d.get('unconnected_items', []))}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true", help="report only, don't write the board")
    ap.add_argument("--drc", action="store_true", help="run kicad-cli DRC after writing")
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
    text, done = apply_moves(outline(text), moves)
    with open(PCB, "w", encoding="utf-8", newline="") as f:
        f.write(text)
    print(f"wrote {PCB.relative_to(ROOT)}: outline {W:g} x {H:g}, {len(done)} footprints")
    if a.drc:
        drc()


if __name__ == "__main__":
    main()
