# Prompt: pre-order review of the Lean 18S slave (handoff, 2026-11-12)

Paste everything below the line into the model doing the review. It replaces
`docs/handoff/review-prompt.md` (2026-11-11), which predates the merged review fixes. Before
pasting, fill in **Branch under review** below.

---

You are reviewing an open-source hardware project before its first PCB order. Find the
**major problems**: anything that would make the board not work, be unsafe at 75 V, fail at the
fab or assembly house, or mislead whoever picks the project up next. Other models may get this
same handoff, so make every finding checkable by someone else.

**Branch under review:** `main` *(or `reference-ideas`, if that branch exists and the user wants
it reviewed; then also review its diff against `savepoint/main-2026-11-12`, idea by idea)*

## Mode

**Read-only.** Do not edit, delete, commit, push or switch the user's branch, and do not open the
boards in KiCad and save them. If you need another branch, use `git worktree add` in a temp
folder. Running the check scripts and `kicad-cli` is fine. Scripts that write go to `exports/`
(gitignored); use a temp copy if you want to fill zones or render. Your output is a written
report (format at the end).

## What the project is

- An **18-series Li-ion cell-monitoring "slave"** built around the Analog Devices **ADBMS1818**
  (64-pin LQFP with exposed pad, 0.5 mm pitch). It measures 18 cells (stack up to 75.6 V at
  4.2 V/cell), balances them passively through the chip's internal S-pin switches and external
  resistors, reads up to four NTCs, and talks to a bought master over **isoSPI**
  (transformer-coupled daisy chain, port A in, port B out). The master and how the slave plugs
  into it are in `docs/master-ennoid-xlite.md`; its firmware drives the chip as an LTC6813-1.
- Use: an electric skateboard pack ("Funwheel" harness), so motor noise, vibration and plug-in
  order matter. Long-term: two slaves on a carrier in a 156.5 × 37 × 10 mm slot.
- Baseline: ADBMS1818 datasheet Rev. B, **Figure 112**. Every deviation is meant to be in
  `docs/slave-18s-design-basis.md` ("Deviations from Figure 112") with a reason. The extra
  isoSPI filtering (split termination + centre-tap caps) is deliberate, for motor noise. Don't
  report it as a deviation to remove.
- Built in public: https://focerqc.github.io/testing-BMS-designs/ (Board Boxes dashboard and
  `news.html`).

## Two variants from one schematic

| | **Guard** `slave-18s/` | **Lean** `slave-18s-lean/` |
|---|---|---|
| Purpose | Bench and hot-plug harnesses: tap fuses, zener clamps, TVS, C-pin caps, test points | Known pack, plugged once; small enough for the slot |
| Schematic | The source, hand-edited | **Generated** from Guard by `_tools/kicad_sch/make_lean.py` |
| PCB | 120 × 70 mm, 2 layers, grouped, **not routed** | **70 × 32 mm, 4 layers, fully routed**: the board to be ordered |
| Balance / series R | 33 Ω 2512 / 10 Ω 1206 | 120 Ω 1206 (~31 mA) / 10 Ω 0402 |
| isoSPI transformer | Pulse HM2113ZNL | Bourns SM91502AL |
| R302 (collector) | 100 Ω | 1 kΩ 2512 1 W |

Review **Lean**. Look at Guard only where its schematic (the source) is wrong, since Lean
inherits it.

## What changed since the 2026-11-11 review

Merged into main (`review-fixes-lean`, commits `d54a060`, `d40f6eb`):

- A **VCOLL voltage-range rule** in `make_rules.py`. Lean's VCOLL is the stack minus 0–35.35 V
  (1 kΩ ±1 %, 35 mA peak), so it can sit more than 30 V from mid-stack nets. Stitching vias
  under Q301 went from 31 to 25, and CELL18's In2 lane moved from y 27.6 to 27.8.
- Design basis corrections: the datasheet's < 2 cm isoSPI limit is transformer-to-connector,
  not chip-side length. Also C0_F's balancing return, 0402 series parts, and trace fuses deferred.
- `_tools/kicad_sch/isospi_shield_check.py` (`197b697`): checks each crossing between an isoSPI
  track and a foreign net for filled, connected V− copper on a layer between them. The design
  basis count was corrected to its result in `44bc4fb`.

Since then only the dashboard and site changed, plus a `.gitignore` commit. No design files changed.

## Repository map

| Path | What it is |
|---|---|
| `AGENTS.md` | Working rules and a long log of tool pitfalls. **Read it first.** |
| `docs/slave-18s-design-basis.md` | The main engineering document (~1100 lines). The "Variants" section has the dated Lean history, including "Review fixes"; "Open items" is at the end |
| `docs/slave-18s-lean-layout-plan.md` | Original Lean layout plan; stale (see below) |
| `docs/master-ennoid-xlite.md` | The master and how the slave fits |
| `slave-18s/` | Guard project, shared `symbols/` and `footprints.pretty/`, Guard's `bom.csv` |
| `slave-18s-lean/` | Lean project: `.kicad_sch` (generated), `.kicad_pcb`, `.kicad_pro`, `.kicad_dru` (generated) |
| `_tools/kicad_sch/` | `check_slave18s.py`, `check_pcb_parity.py`, `make_rules.py`, `make_lean.py`, `lean_place.py`, `lean_route.py`, `isospi_shield_check.py` (all in AGENTS.md) |
| `_tools/pcb_dashboard/`, `site/` | Dashboard and its generated public copy. Out of scope except for docs that contradict the board |
| `_reference/` | Private and gitignored. Don't open, quote or copy anything there |

## Checks to run first

Windows, KiCad 10. pcbnew scripts need KiCad's Python.

```
"C:\Program Files\KiCad\10.0\bin\python.exe" _tools/kicad_sch/lean_route.py --dry
python _tools/kicad_sch/check_slave18s.py --variant lean
python _tools/kicad_sch/check_pcb_parity.py --variant lean
python _tools/kicad_sch/make_rules.py --variant lean --check
python _tools/kicad_sch/isospi_shield_check.py
"C:\Program Files\KiCad\10.0\bin\kicad-cli.exe" pcb drc --severity-all --refill-zones --format json -o <tmp>/drc.json slave-18s-lean/adbms1818-slave-18s-lean.kicad_pcb
```

Results on `main` at `6f0bb2b` (2026-11-12):

- route dry run: 81 nets, 676 segments (F.Cu 512, In1 72, In2 86, B.Cu 6), 61 vias
- `check_slave18s`: 0 problems, ERC 0 errors 0 warnings
- `check_pcb_parity`: PASS, DRC schematic parity 0
- `make_rules --check`: rules OK, 90 nets in banks 0–6 plus line A / line B
- shield check: **6 crossings, 6 uncovered** (five between adjacent layers, one CELL18 on In2
  under ISOB_CM at about (55.05, 24.36) mm with no V− on In1)
- DRC with filled zones: 0 unconnected, 0 parity, only silkscreen: 76 silk_overlap,
  73 silk_over_copper, 4 silk_edge_clearance

Any difference from these numbers is your first finding.

## How the safety rules work (check them, don't trust them)

- **Stack clearance by bank:** each net has a level (its cell tap; V−, VREG, VREF, GPIO and the
  isoSPI chip side are 0; VP_F is the top). Bank = level ÷ 3. Same or next bank: 0.2 mm. Two or
  more banks apart: 0.6 mm (IPC-2221B B2, 31–100 V). No rule names a layer. Lean VCOLL has its
  own range rule (above).
- **isoSPI barrier:** 2.0 mm clearance and creepage between each port's line side (ISOx_LP/LN,
  the transformer's NC pin 5, the plug's mount tabs) and everything else. No pour, and only that
  port's own copper inside the T501/J3 and T601/J4 courtyards, on every layer.
- **Mounting holes:** M2, 1.65 mm hole clearance.
- **Net tie NT1:** CELL0 meets V− only at NT1 by J1 pin 1.
- Tracks: cell sense 0.25, balance 0.3, supply 0.4, isoSPI 0.25 mm; a few 0.2 mm through 0.65 mm
  gaps.

## Lean layout as routed

- J1/J5 (cell plugs, JST PH 10-pin) on the top edge, J2 (NTC) standing on the left edge, J3/J4
  (isoSPI, JST GH) top right with T501/T601 under them and the termination rows under those. U1
  centre-right at x 36, 1.3 mm above the bottom edge. Q301 (FZT853, SOT-223) bottom right with a
  VCOLL zone on all four layers (~118.7 mm² outline per layer, 25 stitching vias).
- **F.Cu** most signals. **In1:** S11–S18, port A pair, DRIVE, a VREG hop, VREF2, GPIO2, one V−
  link. **In2:** U1's bottom pins (S1, S2, C0_F, C1_F, GPIO1–4), CELL18 to R302, port A centre
  tap. **B.Cu:** the V− pour, one IPB hop, VCOLL.
- JLC standard 4-layer: 1 oz outer, 0.5 oz inner. No stack-up section in the board file yet.
- Every part on the front.

## Open items already known (give a verdict, don't just repeat them)

1. **isoSPI crossings:** the six above. A proposed fix moves port A to B.Cu, B's hop to In1, a V−
   shield on In2 and CELL18 west of the ports, but that changes layer roles and needs the owner's
   choice. Is any crossing a real risk, and is there a cheaper fix?
2. **Regulator heat:** at 75.6 V, 22 mA: R302 ~0.48 W, Q301 ~1.07 W; at 35 mA: ~1.23 W and
   ~1.25 W. Q301's rating assumes 52 × 52 mm of 2 oz copper. Real duty cycle from the master
   unknown.
3. **U1 exposed pad:** 16 open 0.2 mm plated holes. Paste and voiding acceptance or a via-fill
   decision needed.
4. **C0_F** runs ~48 mm on In2 beside S1. Noise or error on cell 1?
5. **V− is a back-layer pour, not a star** from U1's pad. Trace the balance return of cell 1 and
   the decoupling returns.
6. **Die heat:** 18 channels at ~31 mA through the internal 4–10 Ω switches. The open item is
   still written for Guard's 89 mA.
7. **Clearances at exactly the minimum** (pass DRC): V− via between R502 and C501, GPIO2 through
   C702's pads, 0.2 mm tap tracks, the In1 V− link at 0.21 mm by the IPB via, IMB 0.615 mm from
   Q301's tab.
8. **No Lean BOM, position file or Gerbers** yet; `slave-18s/bom.csv` is Guard's. FZT853 stock was
   thin (264).
9. **Not confirmed:** J1/J5/J2 pin order against the real harness, isoSPI polarity against the
   master, soldering a slave flat onto a carrier through its plug holes.

## What to review (in this order)

1. **Run the checks.** Report differences.
2. **Schematic against the datasheet** (Guard is the source; check Lean's generated netlist too):
   U1's pin map (`slave-18s/symbols/ADBMS1818.kicad_sym`), the regulator (Q301, R301/C301,
   R302/C302, C303), VREF1/VREF2/IBIAS/ICMP, ISOMD/DTEN/WDT strapping, GPIO5–9, NTC dividers,
   isoSPI termination, NT1. Anything wired wrong, or a value wrong at 75.6 V?
3. **HV safety in copper.** Do the bank and VCOLL rules cover every pair of nets that can be more
   than 30 V apart, including vias, zones and inner layers? Places where neighbours differ by more
   than the rule assumes (an S pin while balancing, CELL9 on both plugs, J1 pin 1 by J5 pin 10)?
   Hole and edge distances?
4. **Signal integrity and measurement.** Items 1, 4 and 5, plus Kelvin sensing of each Cn_F,
   balance current sharing a sense path, isoSPI pairs routed as pairs, centre-tap cap returns,
   VREG/VREF decoupling loops.
5. **Thermal.** Q301, R302, the 1206 balance resistors (~0.12 W each) and U1's die with all 18
   balancing, in a closed pack at 40 °C.
6. **Manufacturability (JLCPCB 4-layer, standard assembly).** Vias 0.5/0.2 mm, 0.2 mm track and
   space, the QFP's exposed-pad vias, 0402 parts, via-in-pad, acid traps and slivers, silk on
   pads, parts availability (LCSC numbers are in the schematic fields).
7. **Mechanical.** 70 × 32 mm, M2 corner holes, connector heights against the 10 mm slot, plug
   access, Q301 and R302 heights.
8. **Docs and repo hygiene.** Where docs contradict the board or each other; obsolete files and
   sections. List only; this feeds a later cleanup.

## Known stale text (don't list these one by one; say if there's more)

- `README.md` says Lean is "70 × 50 mm so far (try 2, placed, not routed)" with bare test pads on
  the back. It's 70 × 32, routed, with no test points.
- The design basis status paragraph is from 2026-11-06. Its open items still list "Board outline
  (placeholder)" and "Final placement, then routing", and the placement checklist is mostly
  unticked. The "Review fixes" bullet mentions 20 crossings, later corrected to 6 in the same
  bullet.
- `docs/slave-18s-lean-layout-plan.md` says try 2, 70 × 50, not routed, 2-layer rules.
- `docs/handoff/review-prompt.md` is the previous version of this prompt.
- Untracked local files: `slave-18s-lean/report.txt`, `slave-18s-lean/*.boxes.json`,
  `.claude/`, other `docs/handoff/*.md`.

## Rules for you

- Never open, quote or copy anything from `_reference/`. Use only what tracked docs say.
- Never invent pin numbers or datasheet values. Cite the datasheet page and figure, or say you
  couldn't check it.
- Not problems: "symbol doesn't match library" and "library not in configuration" ERC warnings,
  `via_dangling` / `track_dangling` in DRC run without `--refill-zones`, KiCad's CRLF line endings.

## Report format

Start with a three-line verdict: can Lean be ordered as it is, and if not, what blocks it.

Then the findings, **most severe first**. For each:

- **Severity:** Blocker (won't work, unsafe, or the fab rejects it) / Major (works badly or
  risky; fix before ordering) / Minor / Docs.
- **Where:** file and line, references, net names, board coordinates in mm.
- **Evidence:** command and output, datasheet page, or measurement. Say plainly when it's
  judgement, not checked.
- **Why it matters,** one or two sentences.
- **Suggested fix** and its cost (board size, layers, parts, routing redone).

Then: (a) the open items 1–9 with a verdict on each (real problem / acceptable / can't tell, and
why); (b) the stale-docs and junk-file list; (c) what you couldn't check.
