"""Scripted routing for the 18S Lean board, try 4 (70 x 32), one piece at a time (2026-11-11).

  "C:\\Program Files\\KiCad\\10.0\\bin\\python.exe" _tools/kicad_sch/lean_route.py [--dry] [--drc] [--pcb FILE]

Every coordinate comes from the pads on the board, so run it again after lean_place.py. It
removes all tracks and vias on the nets it routes and writes them again (same uuids, so a second
run changes nothing). pcbnew only reads; the board file is edited as text. Close KiCad first.

What it routes:
  1. ch 11-18 fan-in to U1's top pins. C18_F...C11_F on the front in eight lanes, lowest lane
     for ch 18. S18...S12 drop to a via under the series row, cross on In1 and come up at a via
     under the chip, just inside U1's top pad row.
  2. V+ supply: U1 pin 1 to C301, C301 to R301 over the top of C301 (0.6 mm from its V- pad),
     CELL18 from R118 to R301.
  3. U1's bottom pins. S2, C1_F, S1, C0_F and GPIO1-4 fan out to a row of eight vias under the
     chip and leave on In2 in eight lanes; the cell nets run to vias at their resistors, the
     GPIO nets to vias at the NTC parts. S3 and C2_F leave on the front along the 1 mm strip
     under U1 and go up the outside of the ch 3-10 bus. VREG runs along the
     strip to C303. GPIO5-9 are joined across their pads and tied to the exposed pad (V-).
  4. ch 3-10 bus: U1's left pins 32-18 on the front, nested inside S3 and C2_F (bus_3_10). S11
     (pin 17) crosses on In1 like S12.
  5. Taps: plug pins to the R2 top pads, down between two R2 parts to the R1 pads (taps).
  6. Supply: VREG from Q301 under its body to C303, DRIVE over it on In1, a via for Q301 pin 2,
     CELL18 on In2 to R302 (supply).

Not routed here: isoSPI, the rest of the NTC wiring, the V- pour.
"""
import argparse
import re
import sys
import uuid
from pathlib import Path

import pcbnew

sys.path.insert(0, str(Path(__file__).resolve().parent))
from kisch import ROOT  # noqa: E402
import lean_place as lp  # noqa: E402  (loads the board: PCB, FP, mm)

PCB, FP, mm = lp.PCB, lp.FP, lp.mm

# ---------------------------------------------------------------- KNOBS (mm)
W_C, W_S, W_FINE = 0.25, 0.3, 0.2    # cell sense, balance, under-the-chip stubs
VIA = (0.5, 0.2)                     # pad / hole: JLC standard price from 0.45 / 0.2
SRC_VIA_Y = 0.625                    # S source via: this far under the series row's pads
CF_VIA_Y = 1.175                     # Cn_F via (ch 0, 1): further down, clear of the S vias
F_LANE0, F_PITCH = 16.2, 0.45        # front fan-in: y of the ch 18 lane, lanes go up from it
I1_LANE0, I1_PITCH = 18.2, 0.6       # In1 fan-in for S18...S12
RING_TOP = 0.545                     # S via this far inside U1's top pad row
ROW_Y = 27.2                         # the via row under the chip for the bottom pins
ROW_X0, ROW_PITCH = 32.35, 0.75
BEND = (28.55, 28.4, 28.3, 28.2, 28.2, 28.3, 28.4, 28.55)   # where each stub leaves its pin's column
I2_LANE0, I2_PITCH = 27.8, 0.45      # In2 lanes leaving the via row to the left
CELL_UP = (13.9, 13.45, 13.0, 12.55)  # In2: where S2, C1_F, S1, C0_F turn up
CELL_TOP = (14.0, 14.45, 14.9, 15.35)  # In2: where they turn left to their vias
BUS_X = (20.9, 20.4)                 # front: S3, C2_F go up here, outside the ch 3-10 bus
BUS_Y = (21.3, 21.8)                 # front: where they turn left to their resistors
STRIP = (30.8, 31.26)                # front: S3, C2_F lanes under U1
VP_OVER = 16.8                       # VP_F passes over C301 here (0.6 mm above its V- pad)
BUS_X0, BUS_PITCH = 21.4, 0.48       # ch 3-10 bus: lane of pin 32 (C3_F), lanes go right from it
BUS_TURN = 0.5                       # ... and each lane turns this much higher than the one outside it
BUS_LEFT, BUS_STRAIGHT = 9, 2        # pins 32-24 turn left, pins 23-22 (S8, C8_F) go straight up
BUS_R_IN, BUS_R_Y = 0.55, 19.65      # pins 21-18: innermost lane this far left of the pads, turns at Y
S11_VIA_Y = 0.33                     # S11 source via: under R211, above C11_F's front lane
TAP_END = 0.39                       # taps: the 45 degree leg ends this far above the R2 top pad
W_GAP = 0.2                          # CELLn down the 0.65 mm gap between two R2 parts
GAP_JOG = 0.16                       # ... jogs to the R1 pad starting this far under the R2 pads
W_SUP = 0.4                          # VREG, DRIVE, CELL18 to R302
Q_VREG_Y = 27.97                     # VREG under Q301's body: 0.6 below the lowest VCOLL via row
DRIVE_VIA_Y = 29.9                   # DRIVE drops to In1 here, in the channel right of U1
CELL18_VIA_Y = 15.6                  # CELL18 drops to In2 on its track from R118 to R301
CELL18_LANE = (22.95, 55.0, 27.6)    # In2: under T601's courtyard, down right of Q301, along to R302

segs, vias = [], []


def pad(ref, net):
    """(cx, cy, x0, y0, x1, y1) of REF's pad on NET (the largest if several)."""
    ps = [p for p in FP[ref].Pads() if p.GetNetname() == net]
    if not ps:
        sys.exit(f"{ref}: no pad on {net}")
    p = max(ps, key=lambda q: q.GetBoundingBox().GetWidth() * q.GetBoundingBox().GetHeight())
    b = p.GetBoundingBox()
    return (mm(p.GetPosition().x), mm(p.GetPosition().y),
            mm(b.GetLeft()), mm(b.GetTop()), mm(b.GetRight()), mm(b.GetBottom()))


def pin(ref, num):
    """(cx, cy, x0, y0, x1, y1) of REF's pad NUM."""
    p = next(q for q in FP[ref].Pads() if q.GetNumber() == num)
    b = p.GetBoundingBox()
    return (mm(p.GetPosition().x), mm(p.GetPosition().y),
            mm(b.GetLeft()), mm(b.GetTop()), mm(b.GetRight()), mm(b.GetBottom()))


def line(net, layer, w, pts):
    for a, b in zip(pts, pts[1:]):
        a, b = (round(a[0], 3), round(a[1], 3)), (round(b[0], 3), round(b[1], 3))
        if a != b:
            segs.append((net, layer, w, a, b))


def route(net, layer, w, pts, c=0.3):
    """Orthogonal way-points; every inner corner is cut at 45 degrees by up to C."""
    pts = [p for i, p in enumerate(pts) if i == 0 or (round(p[0], 4), round(p[1], 4)) != (round(pts[i - 1][0], 4), round(pts[i - 1][1], 4))]
    out = [pts[0]]
    for p, q, r in zip(pts, pts[1:], pts[2:]):
        l1 = abs(q[0] - p[0]) + abs(q[1] - p[1])
        l2 = abs(r[0] - q[0]) + abs(r[1] - q[1])
        k = min(c, l1 / 2, l2 / 2)
        out.append((q[0] + (p[0] - q[0]) / l1 * k, q[1] + (p[1] - q[1]) / l1 * k))
        out.append((q[0] + (r[0] - q[0]) / l2 * k, q[1] + (r[1] - q[1]) / l2 * k))
    out.append(pts[-1])
    line(net, layer, w, out)


def via(net, x, y):
    vias.append((net, round(x, 3), round(y, 3)))


# ---------------------------------------------------------------- the routes
def fan_in():
    u_top = pad("U1", "/C18_F")[3]                    # top edge of U1's top pads
    row_bot = pad("R118", "/C18_F")[5]                # bottom edge of the series row's pads
    ring_y = pad("U1", "/C18_F")[5] + RING_TOP
    for i, n in enumerate(range(18, 10, -1)):         # Cn_F on the front
        net = f"/C{n}_F"
        s, t = pad(f"R1{n:02d}", net), pad("U1", net)
        y = F_LANE0 - F_PITCH * i
        route(net, "F.Cu", W_C, [(s[0], s[1]), (s[0], y), (t[0], y), (t[0], u_top + 0.3)])
    for j, n in enumerate(range(18, 11, -1)):         # Sn through In1
        net = f"/S{n}"
        s, t = pad(f"R2{n:02d}", net), pad("U1", net)
        vy = row_bot + SRC_VIA_Y
        line(net, "F.Cu", W_S, [(s[0], s[1]), (s[0], vy)])
        via(net, s[0], vy)
        y = I1_LANE0 - I1_PITCH * j
        route(net, "In1.Cu", W_S, [(s[0], vy), (s[0], y), (t[0], y), (t[0], ring_y)])
        via(net, t[0], ring_y)
        line(net, "F.Cu", W_C, [(t[0], t[5] - 0.3), (t[0], ring_y)])


def v_plus():
    p1, c, r = pad("U1", "/VP_F"), pad("C301", "/VP_F"), pad("R301", "/VP_F")
    line("/VP_F", "F.Cu", W_S, [(p1[0], p1[1]), (c[0], p1[1])])
    route("/VP_F", "F.Cu", W_S, [(c[0], c[1]), (c[0], VP_OVER), (r[0], VP_OVER), (r[0], r[1])])
    s, t = pad("R118", "/CELL18"), pad("R301", "/CELL18")
    d = s[0] - (t[4] - 0.1)                           # 45 degrees down into R301's pad
    line("/CELL18", "F.Cu", W_C, [(s[0], s[1]), (s[0], t[1] - d), (t[4] - 0.1, t[1]), (t[0], t[1])])


def bottom_pins():
    nets = ["/S2", "/C1_F", "/S1", "/C0_F", "/GPIO1", "/GPIO2", "/GPIO3", "/GPIO4"]
    row_bot = pad("R100", "/C0_F")[5]
    vx = [ROW_X0 + ROW_PITCH * k for k in range(8)]
    lane = [I2_LANE0 + I2_PITCH * k for k in range(8)]
    for k, net in enumerate(nets):                    # pin -> fan -> via row, on the front
        p = pad("U1", net)
        dx = vx[k] - p[0]
        line(net, "F.Cu", W_FINE, [(p[0], p[3] + 0.4), (p[0], BEND[k]), (vx[k], BEND[k] - abs(dx)), (vx[k], ROW_Y)])
        via(net, vx[k], ROW_Y)
    # cell nets on In2: left in a bundle, up, left again to a via at their resistor
    for k, (net, ref, vy) in enumerate((("/S2", "R202", SRC_VIA_Y), ("/C1_F", "R101", CF_VIA_Y),
                                        ("/S1", "R201", SRC_VIA_Y), ("/C0_F", "R100", CF_VIA_Y))):
        t = pad(ref, net)
        ty = row_bot + vy
        route(net, "In2.Cu", W_C, [(vx[k], ROW_Y), (vx[k], lane[k]), (CELL_UP[k], lane[k]),
                                   (CELL_UP[k], CELL_TOP[k]), (t[0], CELL_TOP[k]), (t[0], ty)])
        via(net, t[0], ty)
        line(net, "F.Cu", W_S if "S" in net[:2] else W_C, [(t[0], t[1]), (t[0], ty)])
    # GPIO1-4 on In2 to a via between (or beside) the pads of their NTC filter parts
    g = {n: (pad(f"R70{n}", f"/GPIO{n}"), pad(f"C70{n}", f"/GPIO{n}")) for n in range(1, 5)}
    mid = lambda n: ((g[n][0][0] + g[n][1][0]) / 2, g[n][0][1])
    tgt = {1: mid(1), 2: (g[2][0][4] + 0.5, g[2][0][1]), 3: mid(3), 4: mid(4)}
    j21 = pad("J2", "/GPIO1")
    x1 = tgt[2][0] + 0.7                              # GPIO1 goes up just right of GPIO2's via
    route("/GPIO1", "In2.Cu", W_C, [(vx[4], ROW_Y), (vx[4], lane[4]), (x1, lane[4]), (x1, tgt[1][1] - 1.075),
                                    (tgt[1][0], tgt[1][1] - 1.075), (tgt[1][0], tgt[1][1])])
    route("/GPIO1", "In2.Cu", W_C, [(tgt[1][0], tgt[1][1] - 1.075), (tgt[1][0], j21[1]), (j21[0], j21[1])])
    route("/GPIO2", "In2.Cu", W_C, [(vx[5], ROW_Y), (vx[5], lane[5]), (tgt[2][0], lane[5]), tgt[2]])
    route("/GPIO3", "In2.Cu", W_C, [(vx[6], ROW_Y), (vx[6], lane[6]), (tgt[3][0], lane[6]), tgt[3]])
    route("/GPIO4", "In2.Cu", W_C, [(vx[7], ROW_Y), (vx[7], lane[7]), (tgt[4][0] + 1.1, lane[7]),
                                    (tgt[4][0] + 1.1, tgt[4][1] + 0.725), (tgt[4][0], tgt[4][1] + 0.725), tgt[4]])
    for n in range(1, 5):
        via(f"/GPIO{n}", *tgt[n])
        xs = sorted([g[n][0][0], g[n][1][0], tgt[n][0]]) if n != 2 else sorted([g[2][0][0], tgt[2][0]])
        line(f"/GPIO{n}", "F.Cu", W_C, [(xs[0], tgt[n][1]), (xs[-1], tgt[n][1])])
    # S3 and C2_F on the front: along the strip under U1, up outside the bus, left to the row
    for k, (net, ref) in enumerate((("/S3", "R203"), ("/C2_F", "R102"))):
        p, t = pad("U1", net), pad(ref, net)
        route(net, "F.Cu", W_C, [(p[0], p[5] - 0.4), (p[0], STRIP[k]), (BUS_X[k], STRIP[k]),
                                 (BUS_X[k], BUS_Y[k]), (t[0], BUS_Y[k]), (t[0], t[1])])
    # VREG along the strip to C303: pad width out of the pin, then 0.4 mm
    p, t = pin("U1", "48"), pad("C303", "/VREG")
    route("/VREG", "F.Cu", 0.3, [(p[0], p[5] - 0.4), (p[0], t[1]), (p[0] + 0.6, t[1])])
    line("/VREG", "F.Cu", 0.4, [(p[0] + 0.6, t[1]), (t[0], t[1])])
    # GPIO5-9 (tied to V-): one track across the five pads, one stub from the middle pad to the EP
    gp = sorted((mm(q.GetPosition().x), mm(q.GetPosition().y)) for q in FP["U1"].Pads()
                if q.GetNumber() in ("43", "44", "45", "46", "47"))
    ep_bot = max(mm(q.GetBoundingBox().GetBottom()) for q in FP["U1"].Pads() if q.GetNumber() == "65")
    line("/V-", "F.Cu", W_C, [gp[0], gp[-1]])
    line("/V-", "F.Cu", W_C, [gp[2], (gp[2][0], ep_bot - 0.25)])


def bus_3_10():
    """U1's left pins 32...18 (C3_F...C10_F) on the front, nested inside S3 and C2_F; S11 on In1.

    Every pin leaves left to its lane, goes up and turns towards its resistor. Pins 32-24 turn
    left: the top pin's lane is innermost and turns highest. S8 and C8_F go straight up. The
    targets of pins 21-18 lie right of any lane (R209...R110 sit above U1's top-left corner), so
    they turn right, and there the outer lane turns highest. S11 (pin 17) cannot get past
    C10_F, S10 and C11_F on the front: it drops to a via just inside the pin row and crosses on
    In1 above S12's lane, like S12...S18.
    """
    nets = [(f"/C{n}_F", f"R1{n:02d}") if k % 2 == 0 else (f"/S{n + 1}", f"R2{n + 1:02d}")
            for k, n in enumerate(n for c in range(3, 11) for n in (c, c))][:15]
    pins = [pad("U1", net) for net, _ in nets]
    tgts = [pad(ref, net) for net, ref in nets]
    left = pins[0][2]                                 # left edge of U1's left pad column
    n_l, n_s = BUS_LEFT, BUS_STRAIGHT
    xs = [BUS_X0 + BUS_PITCH * k for k in range(n_l)]
    xs += [tgts[k][0] for k in range(n_l, n_l + n_s)]
    n_r = len(nets) - n_l - n_s
    xs += [left - BUS_R_IN - 0.5 * (len(nets) - 1 - k) for k in range(n_l + n_s, len(nets))]
    ys = [BUS_Y[0] - BUS_TURN * (k + 1) for k in range(n_l)] + [None] * n_s
    ys += [BUS_R_Y - BUS_TURN * (len(nets) - 1 - k) for k in range(n_l + n_s, len(nets))]
    for k in range(len(nets) - 1):                    # lanes in order, 0.475 apart at least
        assert xs[k + 1] - xs[k] >= 0.475 - 1e-9, (nets[k], xs[k], xs[k + 1])
    assert all(tgts[k][0] < xs[k] for k in range(n_l)) and all(tgts[k][0] > xs[k] for k in range(n_l + n_s, len(nets)))
    for k, (net, ref) in enumerate(nets):
        w = W_S if net.startswith("/S") else W_C
        p, t = pins[k], tgts[k]
        pts = [(left + 0.3, p[1]), (xs[k], p[1])]
        if ys[k] is not None:
            pts += [(xs[k], ys[k]), (t[0], ys[k])]
        route(net, "F.Cu", w, pts + [(t[0], t[1])])
    # S11: pin 17 -> via inside the pin row -> In1 -> via under R211 -> R211
    p, t = pad("U1", "/S11"), pad("R211", "/S11")
    ring = (p[4] + RING_TOP, p[1])
    src = (t[0], pad("R111", "/C11_F")[5] + S11_VIA_Y)
    line("/S11", "F.Cu", W_C, [(p[4] - 0.3, p[1]), ring])
    line("/S11", "F.Cu", W_S, [(t[0], t[1]), src])
    lane = I1_LANE0 - I1_PITCH * 7                   # one above S12's In1 lane
    route("/S11", "In1.Cu", W_S, [ring, (ring[0], lane), (src[0], lane), src])
    via("/S11", *ring)
    via("/S11", *src)


def taps():
    """Plug pins to the R2 top pads, then down between two R2 parts to the R1 pad (front).

    Each tap leaves its plug pin straight down and takes one 45 degree leg to its R2 pad, so
    the legs of neighbours stay parallel. From the R2 pad CELLn goes right into the gap to
    R2(n+1) (0.65 mm: a 0.2 mm track), down past the S pads and jogs into R1n's CELLn pad.
    CELL0 (J1 pin 1) runs down between NT1 and R201 to R100 and branches to NT1; CELL9 comes
    from J1 pin 10 and J5 pin 1.
    """
    def leg(net, j, r):
        y_end = r[3] - TAP_END
        route(net, "F.Cu", W_C, [(j[0], j[1]), (j[0], y_end - abs(r[0] - j[0])), (r[0], y_end), (r[0], r[1])], c=0)

    def down(net, x, r1):
        """from x down the gap to R1's pad R1 (centre r1[0], r1[1])."""
        y0 = pad("R201", "/S1")[5] + GAP_JOG
        line(net, "F.Cu", W_GAP, [(x, y0), (r1[0], y0 + abs(r1[0] - x)), (r1[0], r1[1])])
        return y0

    for n in range(1, 19):
        net = f"/CELL{n}"
        r2, r1 = pad(f"R2{n:02d}", net), pad(f"R1{n:02d}", net)
        for j in [(pad("J1", net)), (pad("J5", net))] if n == 9 else [pad("J1" if n < 9 else "J5", net)]:
            leg(net, j, r2)
        gx = (r2[4] + (pad(f"R2{n + 1:02d}", f"/CELL{n + 1}")[2] if n < 18 else r2[4] + 0.65)) / 2
        y0 = down(net, gx, r1)
        route(net, "F.Cu", W_GAP, [(r2[0], r2[1]), (gx, r2[1]), (gx, y0)])
    # CELL0: between NT1 and R201, branch to NT1's CELL0 pad
    j, nt, r1 = pad("J1", "/CELL0"), pad("NT1", "/CELL0"), pad("R100", "/CELL0")
    gx = (pad("NT1", "/V-")[4] + pad("R201", "/CELL1")[2]) / 2
    y0 = down("/CELL0", gx, r1)
    line("/CELL0", "F.Cu", W_GAP, [(gx, j[1]), (gx, y0)])
    line("/CELL0", "F.Cu", W_GAP, [(gx, nt[1]), (nt[0], nt[1])])


def supply():
    """VREG, DRIVE, Q301's pin 2 and CELL18 to R302.

    VREG leaves Q301 pin 3 upwards, runs left under the body (0.6 mm under the stitching vias,
    VCOLL is top of stack), down left of DRIVE's pad and through the gap between C305 and C303
    to C303, which pin 48 already reaches. Pin 55 (ISOMD, tied to VREG) drops to In1 inside the
    pin row and comes up on that track. VREG closes DRIVE's pad in, so DRIVE goes down the
    channel right of U1, crosses on In1 and comes up between VREG and its pad. The VREG track
    also cuts pin 2 off the tab on the front: a via above pin 2 ties it to the inner VCOLL copper.
    CELL18 drops to In2 on its way from R118 to R301, passes under T601's courtyard, goes down
    right of Q301's via grid and along between the VCOLL via rows to R302's CELL18 pad.
    """
    q1, q2, q3 = pad("Q301", "/DRIVE"), pin("Q301", "2"), pad("Q301", "/VREG")
    c305, c303 = pad("C305", "/VREF2"), pad("C303", "/VREG")
    gap_y = (c305[5] + c303[3]) / 2
    vx = q1[2] - 0.6                                  # VREG down left of DRIVE's pad
    route("/VREG", "F.Cu", W_SUP, [(q3[0], q3[1]), (q3[0], Q_VREG_Y), (vx, Q_VREG_Y), (vx, gap_y),
                                    (c303[0], gap_y), (c303[0], c303[1])])
    p55, p48 = pin("U1", "55"), pin("U1", "48")
    ring = (p55[2] - RING_TOP, p55[1])
    line("/VREG", "F.Cu", W_C, [(p55[2] + 0.3, p55[1]), ring])
    low = (ring[0], c303[1])                          # on pin 48's track to C303
    line("/VREG", "In1.Cu", W_C, [ring, low])
    via("/VREG", *ring)
    via("/VREG", *low)
    # DRIVE: pin 49 -> channel -> In1 -> up between VREG and Q301's pin 1
    p49 = pin("U1", "49")
    cx = p49[4] + 0.3
    pocket = (q1[0], Q_VREG_Y + W_SUP / 2 + 0.2 + VIA[0] / 2 + 0.03)
    route("/DRIVE", "F.Cu", 0.3, [(p49[4] - 0.3, p49[1]), (cx, p49[1]), (cx, DRIVE_VIA_Y)])
    route("/DRIVE", "In1.Cu", 0.3, [(cx, DRIVE_VIA_Y), (q1[0], DRIVE_VIA_Y), pocket])
    line("/DRIVE", "F.Cu", 0.3, [pocket, (q1[0], q1[1])])
    via("/DRIVE", cx, DRIVE_VIA_Y)
    via("/DRIVE", *pocket)
    # Q301 pin 2: via above it, 0.6 mm from VREG
    v2 = (q2[0], Q_VREG_Y + W_SUP / 2 + 0.6 + VIA[0] / 2 + 0.03)
    line("/VCOLL", "F.Cu", 0.5, [v2, (q2[0], q2[1])])
    via("/VCOLL", *v2)
    # CELL18 to R302
    s, t = pad("R118", "/CELL18"), pad("R302", "/CELL18")
    top, end = (s[0], CELL18_VIA_Y), (t[0], CELL18_LANE[2])
    y1, x2, y3 = CELL18_LANE
    route("/CELL18", "In2.Cu", W_C, [top, (s[0], y1), (x2, y1), (x2, y3), end])
    line("/CELL18", "F.Cu", W_C, [end, (t[0], t[1])])
    via("/CELL18", *top)
    via("/CELL18", *end)


# ---------------------------------------------------------------- write
def blocks(text, head):
    for m in re.finditer(rf"^\t\({head}\n.*?^\t\)\n", text, re.M | re.S):
        yield m.start(), m.end()


def write(text, mine, ubox):
    """Drop every segment and via on the nets in MINE and add ours. V- is shared with everything
    else, so only its tracks inside U1's courtyard (UBOX) count as ours."""
    uid = lambda *k: uuid.uuid5(uuid.NAMESPACE_URL, "lean_route/" + "/".join(map(str, k)))
    drop = []
    for head in ("segment", "via"):
        for s, e in blocks(text, head):
            blk = text[s:e]
            net = re.search(r'\(net "([^"]*)"\)', blk)
            if not net or net.group(1) not in mine:
                continue
            if net.group(1) == "/VCOLL" and head == "via" and f"(size {VIA[0]:g})" not in blk:
                continue                              # lean_place's stitching vias (0.6 mm)
            if net.group(1) == "/V-":
                a = re.search(r"\((?:start|at) ([-\d.]+) ([-\d.]+)\)", blk)
                if not (ubox[0] < float(a.group(1)) < ubox[2] and ubox[1] < float(a.group(2)) < ubox[3]):
                    continue
            drop.append((s, e))
    for s, e in sorted(drop, reverse=True):
        text = text[:s] + text[e:]
    new = []
    for s in segs:
        net, layer, w, a, b = s
        new.append(f'\t(segment\n\t\t(start {a[0]:g} {a[1]:g})\n\t\t(end {b[0]:g} {b[1]:g})\n\t\t(width {w:g})\n'
                   f'\t\t(layer "{layer}")\n\t\t(net "{net}")\n\t\t(uuid "{uid("seg", *s)}")\n\t)\n')
    for v in vias:
        net, x, y = v
        new.append(f'\t(via\n\t\t(at {x:g} {y:g})\n\t\t(size {VIA[0]:g})\n\t\t(drill {VIA[1]:g})\n'
                   f'\t\t(layers "F.Cu" "B.Cu")\n\t\t(net "{net}")\n\t\t(uuid "{uid("via", *v)}")\n\t)\n')
    at = min(i for i in (text.find(k) for k in ("\n\t(via\n", "\n\t(zone\n", "\n\t(group ", "\n\t(embedded_fonts "))
             if i >= 0) + 1
    return text[:at] + "".join(new) + text[at:], len(drop)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true", help="report only, don't write the board")
    ap.add_argument("--drc", action="store_true", help="run kicad-cli DRC (zones filled) after writing")
    ap.add_argument("--pcb", help="route this board file instead of the Lean board (a scratch copy)")
    a = ap.parse_args()
    if list(PCB.parent.glob("~*.lck")):
        sys.exit("KiCad has the Lean board open (lock file). Close it first.")
    fan_in(); v_plus(); bottom_pins(); bus_3_10(); taps(); supply()
    nets = sorted({s[0] for s in segs} | {v[0] for v in vias})
    length = {}
    for net, layer, w, p, q in segs:
        length[net] = length.get(net, 0) + ((p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2) ** 0.5
    by_layer = {l: sum(1 for s in segs if s[1] == l) for l in ("F.Cu", "In1.Cu", "In2.Cu")}
    print(f"{len(nets)} nets, {len(segs)} segments ({', '.join(f'{l} {n}' for l, n in by_layer.items())}), {len(vias)} vias")
    print("longest: " + ", ".join(f"{n[1:]} {v:.0f} mm" for n, v in sorted(length.items(), key=lambda kv: -kv[1])[:6]))
    if a.dry:
        print("(dry run, board not written)")
        return
    ubox = lp.box(["U1"])
    lp.release()
    with open(PCB, encoding="utf-8", newline="") as f:
        text = f.read()
    text, gone = write(text, set(nets), ubox)
    with open(PCB, "w", encoding="utf-8", newline="") as f:
        f.write(text)
    print(f"wrote {PCB.name}: {gone} old items removed")
    if a.drc:
        lp.drc()


if __name__ == "__main__":
    main()
