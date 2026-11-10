"""Trial placement for the 18S Lean shrink: the whole board from a few knobs (2026-11-08).

Change the KNOBS below and run again; every run places every part from scratch, so a try is
cheap and nothing depends on the previous one. Close KiCad first.

  "C:\\Program Files\\KiCad\\10.0\\bin\\python.exe" _tools/kicad_sch/lean_place.py [--dry] [--drc]

pcbnew only reads pads and courtyards here; it never saves. The board file is edited as text,
like pcb_move.py does: the four Edge.Cuts lines and each footprint's (at ...) line. Parts are
placed by courtyard centre, so connectors (whose origin is pin 1) land where you'd expect.
Afterwards it lists courtyard overlaps and parts outside the outline; --drc also runs
kicad-cli DRC and counts the violations by type (unrouted nets are expected at this stage).

Try 3 floorplan (2026-11-10, 70 x 37: 120 ohm 1206 balance, 0603 series, M2 holes, no test points):
cell plugs top-left with the 18-channel row under them at 2.4 mm pitch, U1 under the row's right
half, both isoSPI ports top-right (GH plug at the top edge, transformer under it, chip side down),
supply parts and Q301 right of U1, NTC plug and its parts bottom-left.
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
W, H = 70.0, 37.0        # board outline, top-left corner at (0, 0); 37 is the XR slot's height
EDGE = 0.3               # courtyards stay this far inside the outline
HOLE_INSET = 2.5         # M2 hole centres this far in from the corner
HOLE_H3 = (W - 2.5, 24.5)  # H3 is not in its corner: isoSPI port A's plug is there
PLUG_X = 5.25            # left courtyard edge of J1 (clear of H4)
PITCH = 2.4              # channel pitch along the row (1206 R2 pad 1.75 + 0.2 + 0.25 + 0.2)
ROW_SHIFT = 0.0          # row centre minus plug-pin centre
TAP = 2.0                # plug courtyards -> R2 (outer) row courtyards: room for the tap traces
ROW_GAP = 0.25           # R2 row courtyards -> R1 (inner) row courtyards
FAN = 6.0                # R1 row courtyards -> U1 courtyard: fan-in of ch 11-18 to U1's top pins
U1_X = 41.0              # U1 centre x (rotation stays 270: cell pins top and left)
GAP = 0.3                # between parts packed into a block
ISO_X = 52.6             # left courtyard edge of port B (T601 + J4); port A (T501 + J3) is right of it
PARK_X = W + 6           # where parked parts wait

# ---------------------------------------------------------------- helpers
mm, nm = pcbnew.ToMM, pcbnew.FromMM
board = pcbnew.LoadBoard(str(PCB))
FP = {f.GetReference(): f for f in board.GetFootprints()}
placed = {}


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


def tl(ref, x, y, rot=0):
    """Top-left courtyard corner of REF to (x, y); returns (right, bottom)."""
    w, h = size(ref, rot)
    put(ref, x + w / 2, y + h / 2, rot)
    return x + w, y + h


# ---------------------------------------------------------------- the floorplan
def floorplan():
    # holes: H4 top-left, H1 bottom-left, H2 bottom-right in their corners, H3 on the right edge
    for ref, x, y in (("H4", HOLE_INSET, HOLE_INSET), ("H1", HOLE_INSET, H - HOLE_INSET),
                      ("H2", W - HOLE_INSET, H - HOLE_INSET), ("H3", *HOLE_H3)):
        put_anchor(ref, x, y)

    # cell plugs on the top edge, left: J1 and J5 keep their 23.5 mm pin-1 spacing;
    # NT1 stands just under J1.1 (C0), CELL0 pad up, left of the C0 tap
    put_anchor("J1", 0, 0); put_anchor("J5", 23.5, 0)
    x0, y0, _, _ = box(["J1", "J5"])
    jx, jy = PLUG_X - x0, EDGE - y0
    put_anchor("J1", jx, jy); put_anchor("J5", jx + 23.5, jy)
    plug_bottom = box(["J1", "J5"])[3]
    put("NT1", jx - 1.3, plug_bottom + 1.0, harness_up("NT1"))
    pins_mid = jx + (23.5 + 9 * 2.0) / 2             # middle of C0 ... C18 on the plugs

    # the 18-channel row: R2 (balance) outer, R1 (10 ohm) inner and half a pitch right,
    # ch 0 at the left, harness pads up
    xc = pins_mid + ROW_SHIFT - 9 * PITCH + PITCH / 4   # R100 (ch 0); the two rows together centred
    h2 = size("R201", harness_up("R201"))[1]
    h1 = size("R101", harness_up("R101"))[1]
    y2 = plug_bottom + TAP + h2 / 2
    y1 = y2 + h2 / 2 + ROW_GAP + h1 / 2
    for n in range(19):
        put(f"R1{n:02d}", xc + n * PITCH, y1, harness_up(f"R1{n:02d}"))
        if n:
            put(f"R2{n:02d}", xc + n * PITCH - PITCH / 2, y2, harness_up(f"R2{n:02d}"))
    row_bottom = y1 + h1 / 2

    # U1 under the row's right half (ch 11-18 drop onto its top pins); ch 0-10 bus down its left side
    u = size("U1", -90)[1]
    put("U1", U1_X, row_bottom + FAN + u / 2, -90)
    ux0, uy0, ux1, uy1 = box(["U1"])

    # isoSPI ports, top-right: GH plug at the top edge, transformer under it with the chip side
    # down, the four termination parts as a 2 x 2 block under the transformer. Port B left, A right.
    x = ISO_X
    for port, jg in (("6", "J4"), ("5", "J3")):
        t = f"T{port}01"
        tw, th = size(t, chip_down(t))
        gw, gh = size(jg, 0)                         # rot 0: pins toward the transformer
        put(jg, x + tw / 2, EDGE + gh / 2, 0)
        put(t, x + tw / 2, EDGE + gh + GAP + th / 2)
        pack([f"R{port}01", f"R{port}02", f"C{port}01", f"C{port}02"], x, EDGE + gh + GAP + th + GAP, 2)
        x += tw + GAP

    # right of U1, at their pins (U1's right side, top to bottom: isoSPI 64-61, ICMP 58, IBIAS 57,
    # VREF1 51, VREF2 50, DRIVE 49; VREG 48 is the bottom-right corner)
    sx = ux1 + GAP
    col = ["R402", "R401", "C304", "C305", "C303"]
    ch = sum(size(r, 0)[1] for r in col) + GAP * (len(col) - 1)
    pack(col, sx, uy1 - ch, 1)
    sx2 = box(col)[2] + GAP
    # V+ filter at pin 1 (U1's top-right corner), right of the ch 18 fan-in
    _, b = tl("R301", sx + 0.25, uy0 - 3.6)
    tl("C301", sx + 0.25, b + GAP)
    # Q301 right of the supply column, pins toward U1 (VREG pin at the bottom, next to C303)
    qw, qh = size("Q301", 0)
    put("Q301", sx2 + qw / 2, H - EDGE - qh / 2, 0)
    pack(["R302", "C302"], sx2, H - EDGE - qh - GAP - size("R302", 0)[1], 2)

    # bottom-left: NTC plug along the bottom edge (right of H1), its filter parts above it
    w, h = size("J2", 0)
    put("J2", 2 * HOLE_INSET + 0.25 + w / 2, H - EDGE - h / 2, 0)
    jx0, jy0, _, _ = box(["J2"])
    ntc = ["R701", "C701", "R702", "C702", "R703", "C703", "R704", "C704", "TH701"]
    rows = -(-len(ntc) // 4)
    pack(ntc, jx0, jy0 - GAP - rows * (size("R701", 0)[1] + GAP), 4)


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
