"""Net classes and HV clearance rules for the ADBMS1818 18S slave.

Writes the net classes and board minimums into the .kicad_pro (JSON read-modify-write)
and generates the .kicad_dru from the nets on the board (Guard by default,
--variant lean for slave-18s-lean/).
Every value and its source is in docs/slave-18s-design-basis.md, "Net classes and
clearance rules".

  python _tools/kicad_sch/make_rules.py           write both files (Guard)
  python _tools/kicad_sch/make_rules.py --variant lean   the same for 18S Lean
  python _tools/kicad_sch/make_rules.py --dry     print the rules, write nothing
  python _tools/kicad_sch/make_rules.py --check   exit 0 only if both files are current
                                                  AND kicad-cli really loads the rules

Why --check matters: kicad-cli silently ignores the whole .kicad_dru if one rule has a
syntax error. The check copies the board to a temp folder, appends a canary rule that
must fire, and fails if it doesn't.

Close KiCad first: it rewrites the .kicad_pro when it saves.
"""
import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from kisch import DEFAULT_SCH, KICAD_CLI, VARIANTS

PRO = DEFAULT_SCH.with_suffix(".kicad_pro")   # set from --variant in main()
PCB = DEFAULT_SCH.with_suffix(".kicad_pcb")
DRU = DEFAULT_SCH.with_suffix(".kicad_dru")

# ---------------------------------------------------------------- net classes
# name, track width, clearance, diff-pair width/gap, patterns. Widths are not set by
# heating (IPC-2221 needs about 0.015 mm for 114 mA at 10 degC rise, 1 oz); see the
# design basis for what each one is based on.
CLASSES = [
    ("HV_CELL", 0.25, 0.20, None, ["/CELL*", "/C*_F", "/TAP*"]),
    ("BALANCE", 0.30, 0.20, None, ["/S?", "/S1?"]),
    ("SUPPLY", 0.40, 0.20, None, ["/VP_F", "/VCOLL", "/DRIVE", "/VREG", "/VBAT_F"]),
    ("ISOSPI_PHY", 0.25, 0.20, (0.25, 0.25),
     ["/IPA", "/IMA", "/IPB", "/IMB", "/ISO?_CM", "/ISO?_CT"]),
    ("ISOSPI_LINE", 0.25, 0.20, (0.25, 0.25), ["/ISO?_LP", "/ISO?_LN"]),
]
DEFAULT_TRACK = 0.25
DEFAULT_CLEARANCE = 0.20

# Board minimums (Board Setup > Constraints). JLCPCB capabilities page, read 2026-11-06:
# 2 oz outer copper 0.16/0.16 mm trace/space; 2-layer via hole 0.15 mm min, 0.2 mm
# preferred, no surcharge for a 0.2 mm hole when the via is >= 0.45 mm across.
# Multilayer (Lean is 4 layers since 2026-11-10; same page, read 2026-11-10): trace/space
# 0.09 mm at 1 oz and 0.15 mm at 2 oz; via hole 0.15 mm min, 0.2 mm preferred, via >= hole +
# 0.1 mm; outer copper 1 or 2 oz, inner 0.5 oz by default (1 or 2 oz on request). So the same
# two minimums hold on both boards and leave 2 oz outer copper open for Lean.
BOARD_RULES = {"min_clearance": 0.16, "min_through_hole_diameter": 0.2}
# Copper layers per variant. The custom rules below name no layer, so they apply on every
# copper layer: the 0.6 mm stack clearance (IPC-2221B column B2, external) is kept on the inner
# layers too. Column B1 (internal) would allow 0.1 mm there for 31-100 V, but every via has
# pads on the outer layers anyway, and the VCOLL copper under Q301 is on all four.
COPPER_LAYERS = {"guard": 2, "lean": 4}
LAYERS = COPPER_LAYERS["guard"]   # set from --variant in main()

# ---------------------------------------------------------------- stack levels
# level = tap number: V- = 0, top of stack = 18. bank = level // 3.
LOW = re.compile(r"/(V-|DRIVE|VREG|VREF[12]|IBIAS|ICMP|GPIO\d+|IP[AB]|IM[AB]|ISO[AB]_C[MT])$"
                 r"|unconnected-\(U1-")           # <= 6 V above V-
TAPPED = re.compile(r"/(?:CELL|TAP)(\d+)$|/C(\d+)_F$|/S(\d+)$")
TOP = {"/VP_F", "/VCOLL", "/VBAT_F"}              # top of stack, after R301/R302
# Line side includes the transformer's unconnected LINE_CT pad 5 and the GH connector's
# hold-down tabs (J3/J4 pad MP, no circuit, about 1.5 mm from the signal pads)
LINE = {"A": re.compile(r"/ISOA_L[PN]$|unconnected-\((T501|J3)-"),
        "B": re.compile(r"/ISOB_L[PN]$|unconnected-\((T601|J4)-")}
# isoSPI nets allowed inside the transformer and connector courtyards, per port
# (J6/J7: JST PH alternates to J3/J4, DNP, in parallel with the GH)
PORT = {"A": (("T501", "J3", "J6"), re.compile(r"/(IPA|IMA|ISOA_\w+)$|unconnected-\((T501|J3)-")),
        "B": (("T601", "J4", "J7"), re.compile(r"/(IPB|IMB|ISOB_\w+)$|unconnected-\((T601|J4)-"))}
BARRIER = 2.0       # mm, clearance and creepage, line side vs everything else
HV_FAR = 0.6        # mm, IPC-2221B B2 31-150 V
# mounting holes per variant: screw, hole diameter, copper keep-out radius from the hole centre,
# what that radius clears (Lean is M2 since 2026-11-10)
HOLES = {"guard": ("M3", 3.2, 4.5, "about 7 mm"), "lean": ("M2", 2.2, 2.75, "about 5 mm")}
HOLE = HOLES["guard"]   # set from --variant in main()


def board_nets(pcb=None):
    text = (pcb or PCB).read_text(encoding="utf-8")
    return sorted(set(re.findall(r'\(net "([^"]*)"\)', text)) - {""})


def copper_layers(pcb=None):
    return len(re.findall(r'^		\(\d+ "[\w.]+\.Cu" \w+', (pcb or PCB).read_text(encoding="utf-8"), re.M))


def board_refs(pcb=None):
    return set(re.findall(r'\(property "Reference" "([^"]+)"', (pcb or PCB).read_text(encoding="utf-8")))


def classify(nets):
    """-> ({net: bank}, {port: [line nets]}); exits on a net it can't place."""
    bank, line, unknown = {}, {"A": [], "B": []}, []
    for n in nets:
        port = next((p for p, rx in LINE.items() if rx.search(n)), None)
        m = TAPPED.search(n)
        if port:
            line[port].append(n)
        elif n in TOP:
            bank[n] = 18 // 3
        elif m:
            bank[n] = int(next(g for g in m.groups() if g)) // 3
        elif LOW.search(n):
            bank[n] = 0
        else:
            unknown.append(n)
    if unknown:
        sys.exit(f"make_rules: no stack level for {unknown}. Add them to LOW, TOP or TAPPED.")
    return bank, line


def any_net(side, nets):
    return "(" + " || ".join(f"{side}.NetName == '{n}'" for n in sorted(nets)) + ")"


def dru_text(nets):
    bank, line = classify(nets)
    top = max(bank.values())
    by = {b: [n for n, k in bank.items() if k == b] for b in range(top + 1)}
    upper = [n for n, k in bank.items() if k >= 1] + line["A"] + line["B"]
    out = [
        "(version 1)",
        "# Generated by _tools/kicad_sch/make_rules.py from the nets on the board.",
        "# Don't edit by hand: change the script and run it again.",
        "# Sources: docs/slave-18s-design-basis.md, 'Net classes and clearance rules'.",
        "#",
        "# 1. Stack clearance, IPC-2221B Table 6-1, column B2 (external, uncoated, up to 3050 m):",
        "#    0-30 V needs 0.1 mm (the 0.2 mm net-class clearance covers it), 31-150 V needs 0.6 mm.",
        "#    Each net's level is its tap number (V- = 0 ... top of stack = 18; VREG, VREF, GPIO",
        "#    and the isoSPI chip side are level 0). bank = level // 3. Two nets in the same or",
        "#    neighbouring banks are at most 6 levels apart (an S pin sits up to one level below",
        "#    its tap while balancing): 6 x 4.2 V = 25.2 V < 30 V. Two or more banks apart they",
        "#    can differ by 31-75.6 V, so they get 0.6 mm. Items with no net count as bank 0.",
    ]
    if LAYERS > 2:
        out += [f"#    {LAYERS} copper layers: no rule names a layer, so the inner layers and the zone fills",
                "#    (the VCOLL copper under Q301) keep the same 0.6 mm."]
    for b in range(top - 1):
        far = [n for n, k in bank.items() if k >= b + 2]
        lo, hi = 3 * b, min(3 * b + 2, 18)
        a_side = ("!" + any_net("A", upper)) if b == 0 else any_net("A", by[b])
        others = f"bank {top}" if b + 2 == top else f"banks {b + 2}-{top}"
        out += ["",
                f'(rule "Stack: bank {b} (levels {lo}-{hi}) vs {others}, B2 31-150 V"',
                f"  (constraint clearance (min {HV_FAR}mm))",
                f'  (condition "{a_side} && {any_net("B", far)}"))']
    out += ["",
            "# 2. isoSPI barrier. Each line side (connector to transformer pins 4-6) floats between",
            "#    this module and its neighbour: up to 2 x 75.6 V = 151.2 V. IPC-2221B B2 151-300 V",
            f"#    needs 1.25 mm; {BARRIER} mm leaves margin for motor common-mode transients and ESD",
            "#    on the connector. On a flat board without slots creepage equals the clearance.",
            "#    Listed after the stack rules so it wins where both match."]
    for p in ("A", "B"):
        own = line[p]
        out += ["",
                f'(rule "isoSPI {p} line side vs everything else"',
                f"  (constraint clearance (min {BARRIER}mm))",
                f"  (constraint creepage (min {BARRIER}mm))",
                f'  (condition "{any_net("A", own)} && !{any_net("B", own)}"))']
    out += ["",
            "# 3. ADBMS1818 datasheet Rev. B p. 86, isoSPI layout guidelines: no V- plane under the",
            "#    transformer or the connector (item 2), no foreign traces across the isoSPI lines",
            "#    (item 3). Courtyards stand in for 'under'; the gap between transformer and",
            "#    connector is on the placement checklist."]
    on_board = board_refs()
    for p, (refs, rx) in PORT.items():
        refs = [r for r in refs if r in on_board]      # Lean has no J6/J7
        inside = " || ".join(f"A.intersectsCourtyard('{r}')" for r in refs)
        own = [n for n in nets if rx.search(n)]
        out += ["",
                f'(rule "No copper pour under {" or ".join(refs)}"',
                "  (constraint disallow zone)",
                f'  (condition "{inside}"))',
                "",
                f'(rule "Only isoSPI {p} tracks and vias inside {" and ".join(refs)}"',
                "  (constraint disallow track via)",
                f'  (condition "({inside}) && !{any_net("A", own)}"))']
    out += ["",
            f"# 4. Mounting holes H1-H4 ({HOLE[0]}, NPTH, {HOLE[1]:g} mm): keep copper {HOLE[2]:g} mm from the hole centre so",
            f"#    an {HOLE[0]} screw head or nylon washer ({HOLE[3]} across) never touches copper. {HOLE[2] - HOLE[1] / 2:g} mm",
            f"#    from the hole edge = {HOLE[2]:g} mm - {HOLE[1] / 2:g} mm hole radius.",
            "",
            '(rule "Mounting hole copper keep-out"',
            f"  (constraint hole_clearance (min {HOLE[2] - HOLE[1] / 2:g}mm))",
            "  (condition \"A.memberOfFootprint('H*')\"))"]
    return "\n".join(out) + "\n"


def pro_settings(pro_text):
    p = json.loads(pro_text)
    ns = p["net_settings"]
    template = next(c for c in ns["classes"] if c["name"] == "Default")
    template.update(track_width=DEFAULT_TRACK, clearance=DEFAULT_CLEARANCE)
    classes = [template]
    for prio, (name, width, clr, dp, _) in enumerate(CLASSES):
        c = dict(template, name=name, priority=prio, track_width=width, clearance=clr)
        if dp:
            c.update(diff_pair_width=dp[0], diff_pair_gap=dp[1])
        classes.append(c)
    ns["classes"] = classes
    ns["netclass_patterns"] = [{"netclass": name, "pattern": pat}
                               for name, *_, pats in CLASSES for pat in pats]
    p["board"]["design_settings"]["rules"].update(BOARD_RULES)
    return json.dumps(p, indent=2) + "\n"


def canary_ok(dru):
    """Run kicad-cli DRC on a temp copy with a canary rule appended. True if it fires."""
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        for f in (PCB, PRO):
            shutil.copy(f, t / f.name)
        canary = ('\n(rule "canary"\n  (constraint clearance (min 50mm))\n'
                  "  (condition \"A.NetName == '/V-' && B.NetName == '/VREG'\"))\n")
        (t / DRU.name).write_text(dru + canary, encoding="utf-8")
        rep = t / "drc.json"
        subprocess.run([KICAD_CLI, "pcb", "drc", "--format", "json", "-o", str(rep),
                        str(t / PCB.name)], capture_output=True)
        d = json.loads(rep.read_text(encoding="utf-8"))
        return any("'canary'" in v["description"] for v in d["violations"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--variant", choices=tuple(VARIANTS), default="guard",
                    help="guard = slave-18s, lean = slave-18s-lean")
    a = ap.parse_args()
    global PRO, PCB, DRU, HOLE, LAYERS
    HOLE, LAYERS = HOLES[a.variant], COPPER_LAYERS[a.variant]
    sch = VARIANTS[a.variant]
    PRO, PCB, DRU = (sch.with_suffix(s) for s in (".kicad_pro", ".kicad_pcb", ".kicad_dru"))
    print(f"{a.variant}: {PCB.relative_to(sch.parents[1]).as_posix()}")
    have = copper_layers()
    if have != LAYERS:
        print(f"FAIL: the board has {have} copper layers, {a.variant} is {LAYERS}"
              + (" (run lean_place.py)" if a.variant == "lean" else ""))
        return 1
    nets = board_nets()
    dru = dru_text(nets)
    pro_old = PRO.read_text(encoding="utf-8")
    pro_new = pro_settings(pro_old)
    bank, line = classify(nets)
    print(f"{len(nets)} nets: " + ", ".join(
        f"bank {b}: {sum(1 for k in bank.values() if k == b)}" for b in sorted(set(bank.values())))
        + f", line A: {len(line['A'])}, line B: {len(line['B'])}")
    if a.dry:
        print(dru)
        return 0
    if a.check:
        ok = True
        if not DRU.exists() or DRU.read_text(encoding="utf-8") != dru:
            print("FAIL: .kicad_dru is not what make_rules.py generates (run it)"); ok = False
        if pro_new != pro_old:
            print("FAIL: .kicad_pro net classes/board minimums differ (run make_rules.py)"); ok = False
        if not canary_ok(DRU.read_text(encoding="utf-8") if DRU.exists() else ""):
            print("FAIL: kicad-cli did not load the rules (canary did not fire)"); ok = False
        print("rules: OK" if ok else "rules: FAIL")
        return 0 if ok else 1
    if not canary_ok(dru):
        sys.exit("make_rules: kicad-cli rejected the generated rules; nothing written")
    DRU.write_text(dru, encoding="utf-8", newline="\n")
    if pro_new != pro_old:
        PRO.write_text(pro_new, encoding="utf-8", newline="\n")
    print(f"wrote {DRU.name} and {PRO.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
