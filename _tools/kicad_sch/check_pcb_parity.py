"""PCB-vs-schematic check for the ADBMS1818 18S slave.

  1. kicad-cli netlist of the schematic -> {ref.pin: net} and {ref: footprint}.
  2. Every footprint in the .kicad_pcb: present, footprint name as in the schematic.
  3. Every numbered pad: net in the .kicad_pcb == net from the netlist (exact name,
     so "/V-" vs "V-" counts as a mismatch). Unnumbered pads (thermal vias, paste)
     must have no net or the same net as the numbered pad they belong to.
  4. Every footprint on the front side (F.Cu): the slave is single-sided so it can sit
     flat on a carrier PCB. Exception (Lean, 2026-11-09): test points TP<n> are bare copper
     pads, no part, and sit on the back; they must be on B.Cu there and on F.Cu on Guard.
  5. kicad-cli DRC with --schematic-parity: 0 parity items.
Other DRC items (unrouted, courtyards, silk) are only counted by type.
Exit code 0 only if 2-5 pass. PWR_FLAGs have no footprint and are not in the netlist.

usage: python _tools/kicad_sch/check_pcb_parity.py [--variant guard|lean] [--sch FILE] [--pcb FILE] [--no-drc]
"""
import argparse
import re
import json
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

from kisch import KICAD_CLI, VARIANTS, kid, kids, load

TMP = Path(tempfile.gettempdir())


def netlist(sch):
    out = TMP / "slave18s_parity.net"
    subprocess.run([KICAD_CLI, "sch", "export", "netlist", "--format", "kicadsexpr", "-o", str(out), str(sch)],
                   check=True, capture_output=True)
    root = load(out)
    fps = {kid(c, "ref")[1]: kid(c, "footprint")[1] for c in kids(kid(root, "components"), "comp")}
    pins = {}
    for n in kids(kid(root, "nets"), "net"):
        name = kid(n, "name")[1]
        for node in kids(n, "node"):
            pins[f'{kid(node, "ref")[1]}.{kid(node, "pin")[1]}'] = name
    return fps, pins


def board(pcb):
    root = load(pcb)
    fps, pads, extra, back = {}, {}, [], []
    for fp in kids(root, "footprint"):
        ref = next(p[2] for p in kids(fp, "property") if p[1] == "Reference")
        fps[ref] = fp[1]
        if kid(fp, "layer")[1] != "F.Cu":
            back.append(ref)
        for pad in kids(fp, "pad"):
            net = kid(pad, "net")
            name = net[-1] if net else ""
            if name.startswith("unconnected-"):
                # a no-connect pin with several pads (J3/J4 MP tabs) gets one net per pad: X, X_1
                name = re.sub(r"_\d+$", "", name)
            if pad[1] == "":
                extra.append((ref, name))
            else:
                key = f"{ref}.{pad[1]}"
                if pads.setdefault(key, name) != name:
                    pads[key] = f"<conflict {pads[key]} / {name}>"
    return fps, pads, extra, back


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", choices=tuple(VARIANTS), default="guard",
                    help="guard = slave-18s, lean = slave-18s-lean (--sch/--pcb override it)")
    ap.add_argument("--sch", default=None)
    ap.add_argument("--pcb", default=None)
    ap.add_argument("--no-drc", action="store_true")
    a = ap.parse_args()
    a.sch = a.sch or str(VARIANTS[a.variant])
    a.pcb = a.pcb or str(Path(a.sch).with_suffix(".kicad_pcb"))
    print(f"{a.variant if a.sch == str(VARIANTS[a.variant]) else 'custom'}: {a.pcb}")
    ok = True

    sfp, spin = netlist(a.sch)
    bfp, bpad, extra, back = board(a.pcb)

    missing = sorted(set(sfp) - set(bfp))
    surplus = sorted(set(bfp) - set(sfp))
    wrongfp = sorted(r for r in sfp if r in bfp and sfp[r] != bfp[r])
    print(f"footprints: schematic {len(sfp)}, board {len(bfp)}; missing {missing or 0}, "
          f"extra {surplus or 0}, wrong footprint {wrongfp or 0}")
    ok &= not (missing or surplus or wrongfp)

    mism = []
    for key in sorted(set(spin) | set(bpad)):
        s, b = spin.get(key, "<not in netlist>"), bpad.get(key, "<no pad>")
        if s.startswith("unconnected-") and b in ("", s):
            continue
        if s != b:
            mism.append((key, s, b))
    for key, s, b in mism[:40]:
        print(f"  MISMATCH {key}: schematic {s!r}, board {b!r}")
    print(f"pads: {len(bpad)} numbered pads checked, {len(mism)} mismatches")
    ok &= not mism

    badx = [(r, n) for r, n in extra if n and n != bpad.get(f"{r}.65", n)]
    print(f"unnumbered pads: {len(extra)} (nets off the EP: {len(badx)})")
    ok &= not badx

    lean = a.variant == "lean"
    tp = lambda r: re.fullmatch(r"TP\d+", r)
    wrong = [r for r in back if not (lean and tp(r))] + [r for r in bfp if lean and tp(r) and r not in back]
    print(f"front side: {len(bfp) - len(back)} of {len(bfp)} footprints on F.Cu"
          + (f"; on the back: {sorted(back)}" if back else "")
          + (f"; WRONG SIDE: {sorted(wrong)}" if wrong else (" (Lean test points are on the back)" if lean else "")))
    ok &= not wrong

    if not a.no_drc:
        rep = TMP / "slave18s_drc.json"
        subprocess.run([KICAD_CLI, "pcb", "drc", "--schematic-parity", "--severity-all", "--format", "json",
                        "-o", str(rep), a.pcb], check=True, capture_output=True)
        d = json.loads(rep.read_text(encoding="utf-8"))
        par = d.get("schematic_parity", [])
        print(f"DRC schematic parity: {len(par)} {dict(Counter(x['type'] for x in par))}")
        for x in par[:10]:
            print("  ", x["description"], [i["description"] for i in x["items"]])
        print(f"DRC other (expected before placement/routing): "
              f"{dict(Counter(x['type'] for x in d.get('violations', [])))}, "
              f"unconnected {len(d.get('unconnected_items', []))}")
        ok &= not par

    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
