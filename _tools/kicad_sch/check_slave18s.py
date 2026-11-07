"""Ground-truth check of the ADBMS1818 18S slave schematic against its wiring table.

Runs kicad-cli (netlist + ERC) and checks:
  1. every ref.pin in the table is on the expected net;
  2. every no-connect pin is alone on its net AND has an NC flag on its pin end;
  3. no extra pins of the checked parts sit on an expected net;
  4. every pin in the netlist is covered by the table, all 65 U1 pins are accounted for,
     and the only one-pin nets are the intended no-connects;
  5. ERC (all severities) is empty.
Exit code 0 only if everything passes. Re-run after any schematic edit.

usage: python _tools/kicad_sch/check_slave18s.py [--sch FILE] [--blocks 1 2 3 4 5 6] [--erc]
Wiring table source: docs/slave-18s-design-basis.md ("Schematic nets") and the datasheet.
"""
import argparse
import json
import subprocess
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

from kisch import DEFAULT_SCH, KICAD_CLI, kid, kids, load, no_connects, parse, symbols

TMP = Path(tempfile.gettempdir())
E = {b: {} for b in range(1, 7)}      # block -> {ref.pin: net}
NC = {b: set() for b in range(1, 7)}  # block -> {ref.pin}
BLOCKS = sorted(E)


def cell(n):
    return f"CELL{n}"   # fused side of tap n. CELL0 is the C0 sense tap; V- has its own fuse F120


# Block 1: power, references, bias, configuration pins
E[1].update({"R301.1": "VBAT_F", "R301.2": "VP_F", "U1.1": "VP_F", "C301.1": "VP_F", "C301.2": "V-",
             "R302.1": "VBAT_F", "R302.2": "VCOLL", "C302.1": "VCOLL", "C302.2": "V-",
             "Q301.1": "DRIVE", "Q301.2": "VCOLL", "Q301.3": "VREG", "U1.49": "DRIVE", "U1.48": "VREG",
             "C303.1": "VREG", "C303.2": "V-", "C304.1": "VREF1", "C304.2": "V-", "U1.51": "VREF1",
             "C305.1": "VREF2", "C305.2": "V-", "U1.50": "VREF2",
             "R401.1": "IBIAS", "R401.2": "ICMP", "R402.1": "ICMP", "R402.2": "V-",
             "U1.57": "IBIAS", "U1.58": "ICMP", "U1.55": "VREG", "U1.52": "V-",
             "U1.59": "V-", "U1.60": "V-", "U1.65": "V-"})
NC[1] |= {"U1.53", "U1.54", "U1.56"}
# GPIO5-9 spare: tied to V- because the ENNOID firmware leaves the internal pull-downs off
E[1].update({f"U1.{p}": "V-" for p in range(43, 48)})

# Block 2: cell inputs. Cn = pin 38-2n, Sn = pin 39-2n
for n in range(19):
    E[2][f"R1{n:02d}.1"] = cell(n)
    E[2][f"R1{n:02d}.2"] = f"C{n}_F"
    E[2][f"U1.{38 - 2 * n}"] = f"C{n}_F"
    if n:
        E[2].update({f"C1{n:02d}.1": f"C{n}_F", f"C1{n:02d}.2": "V-",
                     f"R2{n:02d}.1": cell(n), f"R2{n:02d}.2": f"S{n}", f"U1.{39 - 2 * n}": f"S{n}"})
assert E[2]["U1.38"] == "C0_F" and E[2]["U1.2"] == "C18_F" and E[2]["U1.37"] == "S1" and E[2]["U1.3"] == "S18"

# Block 3: isoSPI, datasheet Fig. 104(B). Same polarity on both ports.
for port, (ra, rb), (ccm, cct), t, j, jb, ip, im in (("A", ("R501", "R502"), ("C501", "C502"), "T501", "J3", "J6", "62", "61"),
                                                     ("B", ("R601", "R602"), ("C601", "C602"), "T601", "J4", "J7", "64", "63")):
    ipn, imn = f"IP{port}", f"IM{port}"
    cm, ct, lp, ln = (f"ISO{port}_{s}" for s in ("CM", "CT", "LP", "LN"))
    E[3].update({f"U1.{ip}": ipn, f"U1.{im}": imn,
                 f"{ra}.1": ipn, f"{ra}.2": cm, f"{rb}.1": cm, f"{rb}.2": imn,
                 f"{ccm}.1": cm, f"{ccm}.2": "V-", f"{cct}.1": ct, f"{cct}.2": "V-",
                 f"{t}.1": ipn, f"{t}.3": imn, f"{t}.2": ct, f"{t}.6": lp, f"{t}.4": ln,
                 f"{j}.1": lp, f"{j}.2": ln,           # JST GH 2P (master cable)
                 f"{jb}.1": lp, f"{jb}.2": ln})        # JST PH 2P alternate (J6/J7), DNP
    NC[3] |= {f"{t}.5", f"{j}.MP"}                       # GH hold-down tabs: no circuit

# Block 4: thermistors
for k, pin in zip((1, 2, 3, 4), (39, 40, 41, 42)):
    E[4].update({f"R70{k}.1": "VREF2", f"R70{k}.2": f"GPIO{k}", f"C70{k}.1": f"GPIO{k}",
                 f"C70{k}.2": "V-", f"U1.{pin}": f"GPIO{k}"})
E[4].update({"J2.1": "GPIO1", "J2.2": "V-", "J2.3": "GPIO2", "J2.4": "V-", "J2.5": "GPIO3", "J2.6": "V-",
             "TH701.1": "GPIO4", "TH701.2": "V-"})

# Block 5: cell-tap connectors (connector side of the fuses; J1.10 and J5.1 are both tap 9)
for k in range(1, 11):
    E[5][f"J1.{k}"] = f"TAP{k - 1}"
    E[5][f"J5.{k}"] = f"TAP{k + 8}"

# Block 6: hot-plug protection and test points (design basis, "Protection and test points")
for n in range(19):                                   # tap fuses, AN-2093 Fig. 11
    E[6].update({f"F1{n:02d}.1": f"TAP{n}", f"F1{n:02d}.2": cell(n)})
E[6].update({"F119.1": "TAP18", "F119.2": "VBAT_F",     # supply branches
             "F120.1": "TAP0", "F120.2": "V-",
             "D301.1": "VBAT_F", "D301.2": "V-"})          # TVS, K = pin 1
for n in range(1, 19):                               # zener clamps, K = pin 1 at Cn_F
    E[6].update({f"D1{n:02d}.1": f"C{n}_F", f"D1{n:02d}.2": f"C{n - 1}_F"})
for k, net in enumerate(["V-", "V-", "VREG", "VREF1", "VREF2", "DRIVE", "IPA", "IMA", "IPB", "IMB",
                         "VCOLL", "C6_F", "C12_F", "C18_F"], 1):
    E[6][f"TP{k}.1"] = net


def kicad(sch):
    net, erc = TMP / "check_slave18s.net", TMP / "check_slave18s.erc.json"
    r = subprocess.run([KICAD_CLI, "sch", "export", "netlist", "--format", "kicadsexpr", "--output", str(net), sch],
                       capture_output=True, text=True)
    if r.returncode:
        sys.exit("netlist export failed (does the file load?)\n" + r.stdout + r.stderr)
    subprocess.run([KICAD_CLI, "sch", "erc", "--format", "json", "--severity-all", "--output", str(erc), sch],
                   capture_output=True, text=True)
    tree = parse(net.read_text(encoding="utf-8"))
    pin2net, net2pins = {}, defaultdict(list)
    for n in kids(kid(tree, "nets"), "net"):
        name = kid(n, "name")[1].lstrip("/")
        for nd in kids(n, "node"):
            key = f"{kid(nd, 'ref')[1]}.{kid(nd, 'pin')[1]}"
            pin2net[key] = name
            net2pins[name].append(key)
    return pin2net, net2pins, json.loads(erc.read_text(encoding="utf-8"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sch", default=str(DEFAULT_SCH))
    ap.add_argument("--blocks", nargs="+", type=int, default=BLOCKS)
    ap.add_argument("--erc", action="store_true", help="print every ERC violation")
    a = ap.parse_args()
    full = sorted(a.blocks) == BLOCKS

    pin2net, net2pins, erc = kicad(a.sch)
    exp, ncs = {}, set()
    for b in a.blocks:
        exp.update(E[b]); ncs |= NC[b]
    bad = 0

    for key, want in sorted(exp.items()):                       # 1
        got = pin2net.get(key, "<missing>")
        if got != want:
            bad += 1; print(f"MISMATCH {key}: want {want}, got {got}")

    t = load(a.sch)                                             # 2
    ends = {f"{s['ref']}.{n}": (p["ex"], p["ey"]) for s in symbols(t) for n, p in s["pins"].items()}
    flags = {(round(x, 2), round(y, 2)) for x, y in no_connects(t)}
    for key in sorted(ncs):
        got = pin2net.get(key, "<missing>")
        ex, ey = ends[key]
        if not got.startswith("unconnected-") or len(net2pins[got]) != 1 or (round(ex, 2), round(ey, 2)) not in flags:
            bad += 1; print(f"NC FAIL {key}: net={got} flag={(round(ex, 2), round(ey, 2)) in flags}")

    want = defaultdict(set)                                     # 3
    for key, net in exp.items():
        want[net].add(key)
    refs = {k.split(".")[0] for k in exp} | {k.split(".")[0] for k in ncs}
    for net, pins in want.items():
        extra = {p for p in net2pins.get(net, []) if p.split(".")[0] in refs} - pins
        if extra:
            bad += 1; print(f"EXTRA on {net}: {sorted(extra)}")

    if full:                                                    # 4
        covered = set(exp) | ncs
        stray = sorted(set(pin2net) - covered)
        if stray:
            bad += 1; print("pins not in the table:", stray)
        missing_u1 = [p for p in range(1, 66) if f"U1.{p}" not in pin2net]
        if missing_u1:
            bad += 1; print("U1 pins missing from the netlist:", missing_u1)
        lonely = sorted(k for n, v in net2pins.items() for k in v if len(v) == 1 and k not in ncs)
        if lonely:
            bad += 1; print("one-pin nets that are not intended no-connects:", lonely)
        print(f"netlist: {len(pin2net)} pins, {len(net2pins)} nets; table covers {len(covered)}")

    counts = defaultdict(int)                                   # 5
    for sh in erc.get("sheets", []):
        for v in sh.get("violations", []):
            counts[f"{v['severity']}:{v['type']}"] += 1
            if a.erc:
                print("  ERC", v["severity"], v["type"], "|", "; ".join(i["description"] for i in v.get("items", [])))
    if full and counts:
        bad += 1
    print(f"checked {len(exp)} pin->net rows + {len(ncs)} no-connects (blocks {a.blocks}): {bad} problems")
    print("ERC:", dict(counts) or "0 errors, 0 warnings")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
