# Prompt: design review of the 18S BMS slave (handoff, 2026-11-11)

Paste everything below the line into the model doing the review. It assumes the model has
this repository checked out and can run commands. Edit the "Mode" paragraph if you want it to
fix things rather than only report them.

---

You are reviewing an open-source hardware project before its first PCB order. Find the
**major problems**: anything that would make the board not work, be unsafe at 75 V, fail at the
fab or assembly house, or mislead whoever picks the project up next. You are one of several
models getting this handoff, so make every finding checkable by someone else.

## Mode

**Read-only.** Do not edit, delete, commit or push anything, and do not open the boards in
KiCad and save them. Running the check scripts and `kicad-cli` is fine. Those that write go to
`exports/` (gitignored); make copies in a temp folder if you want to fill zones or render.
Your output is a written report (format at the end).

## What the project is

- An **18-series Li-ion cell-monitoring "slave" board** built around the Analog Devices
  **ADBMS1818** (64-pin LQFP with exposed pad, 0.5 mm pitch). It measures 18 cells (stack up
  to 75.6 V at 4.2 V/cell), balances them passively through the chip's internal S-pin
  switches and external resistors, reads up to four NTC thermistors, and talks to a master
  over **isoSPI** (transformer-coupled daisy chain, port A in, port B out).
- The **master is bought, not designed here**: an ENNOID Master-XLITE-ISC
  (`docs/master-ennoid-xlite.md`). Its firmware drives the chip as an LTC6813-1.
- The intended use is an electric skateboard pack ("Funwheel" harness), so motor noise,
  vibration and plug-in order matter. Long-term goal: two slaves on a carrier in a
  156.5 × 37 × 10 mm slot ("XR slot").
- Baseline circuit: ADBMS1818 datasheet Rev. B, **Figure 112** (typical application). Every
  deviation is meant to be written into `docs/slave-18s-design-basis.md` with a reason
  ("Deviations from Figure 112"). Extra isoSPI filtering (split termination + centre-tap
  caps) is deliberate, copied from a working reference board by a hobbyist designer called
  Racc, and is not a deviation to remove.
- Built in public: GitHub Pages site at https://focerqc.github.io/testing-BMS-designs/
  (Board Boxes dashboard plus `news.html`).

## Two board variants from one schematic

| | **Guard** `slave-18s/` | **Lean** `slave-18s-lean/` |
|---|---|---|
| Purpose | Bench and hot-plug harnesses: tap fuses, zener clamps, TVS, C-pin caps, test points | Known pack, plugged once; small enough for the XR slot |
| Schematic | The source, hand-edited | **Generated** from Guard by `_tools/kicad_sch/make_lean.py`. Never hand-edit it |
| PCB | 120 × 70 mm, 2 layers, parts grouped roughly, **not routed** | **70 × 32 mm, 4 layers, fully routed** (2026-11-11), the board about to be ordered |
| Balance / series resistors | 33 Ω 2512 / 10 Ω 1206 | 120 Ω 1206 (~31 mA) / 10 Ω 0402 |
| isoSPI transformers | Pulse HM2113ZNL | Bourns SM91502AL |
| Regulator collector resistor R302 | 100 Ω | 1 kΩ 2512 1 W (own deviation 14) |

The review is mainly about **Lean**. Look at Guard only where its schematic (the source) is
wrong, since Lean inherits it.

## Repository map

| Path | What it is |
|---|---|
| `AGENTS.md` | Working rules and a long log of tool pitfalls. **Read it first.** |
| `README.md` | Overview. Partly stale (see "Known stale text") |
| `docs/slave-18s-design-basis.md` | The main engineering document (~1000 lines): chip facts, Figure 112 baseline, deviations, balance sizing, parts with JLC numbers, connectors, nets, PCB history, net classes and clearance rules, placement checklist, open items. The "Variants" section has the dated history of Lean tries 1–4 and of the routing |
| `docs/slave-18s-lean-layout-plan.md` | The original step-by-step layout plan for Lean. Largely superseded by scripts; status line says try 2 |
| `docs/master-ennoid-xlite.md` | The master and how the slave fits |
| `slave-18s/` | Guard KiCad 10 project, shared symbol/footprint libraries (`symbols/`, `footprints.pretty/`), STEP model, `bom.csv` (Guard's JLC BOM) |
| `slave-18s-lean/` | Lean KiCad project: `.kicad_sch` (generated), `.kicad_pcb`, `.kicad_pro`, `.kicad_dru` (generated), 3D renders |
| `_tools/kicad_sch/` | Python helpers, all described in AGENTS.md. Key ones: `check_slave18s.py` (netlist + ERC vs wiring table), `check_pcb_parity.py` (PCB vs schematic), `make_rules.py` (net classes + custom DRC rules), `make_lean.py`, `lean_place.py` (places every Lean footprint, outline, VCOLL zones), `lean_route.py` (draws every Lean track, via and the V− zone from pad positions) |
| `_tools/pcb_dashboard/` | "Board Boxes" local dashboard (`server.py`, `app.js`) and the site exporter (`export_site.py`, `check_hosted.cjs`) |
| `site/` | Generated GitHub Pages copy. `news.html` is hand-written |
| `exports/` | Scratch outputs, gitignored |
| `_reference/` | `racc/`, `datasheets/`, `firmware/` are **private and gitignored**. Never quote, copy or publish anything from them |
| `savepoint/*` branches | Old states (120 × 70 Lean plan, pre-placement, pre-PCB, pre-wiring) |

## Tools and environment

- Windows, KiCad 10 at `C:\Program Files\KiCad\10.0\`. The `pcbnew` scripts must run with
  KiCad's Python: `"C:\Program Files\KiCad\10.0\bin\python.exe"`. The dashboard and exporter
  use the normal Python (`requirements.txt`).
- **`kicad-cli` is ground truth.** Trust its ERC, DRC and netlist over any other tool or
  summary, including the docs.
- `lean_place.py` and `lean_route.py` edit the board **as text**. A second run changes
  nothing. Lean's layout is reproduced by running them in that order, so a problem in the
  layout is a problem in those scripts' knobs.
- Zones are saved **unfilled**. Always run DRC with `--refill-zones`, or every stitching via
  shows up as dangling.

### Checks to run first (all should pass today)

```
"C:\Program Files\KiCad\10.0\bin\python.exe" _tools/kicad_sch/lean_route.py --dry
python _tools/kicad_sch/check_slave18s.py --variant lean
python _tools/kicad_sch/check_pcb_parity.py --variant lean
python _tools/kicad_sch/make_rules.py --variant lean --check
"C:\Program Files\KiCad\10.0\bin\kicad-cli.exe" pcb drc --severity-all --refill-zones --format json -o <tmp>/drc.json slave-18s-lean/adbms1818-slave-18s-lean.kicad_pcb
```

Expected on 2026-11-11: parity PASS, rules OK, DRC with zones filled has 0 unconnected items
and only silkscreen violations (76 silk_overlap, 73 silk_over_copper, 4 silk_edge_clearance).
If you see anything else, that is your first finding.

## How the safety rules work (check them, don't just trust them)

- **Stack clearance by "bank":** each net has a level (its cell tap number; V−, VREG, VREF,
  GPIO and the isoSPI chip side are level 0; VP_F and VCOLL count as the top). Bank =
  level ÷ 3. Same or neighbouring bank: 0.2 mm (net class). Two or more banks apart: 0.6 mm
  (IPC-2221B B2, 31–100 V), in the generated `.kicad_dru`. No rule names a layer, so the
  same applies on inner layers.
- **isoSPI barrier:** 2.0 mm clearance and creepage between each port's line side
  (ISOx_LP/LN, the transformer's unconnected pin 5, the plug's mount tabs) and everything
  else. No pour, and only that port's own tracks and vias, inside the T501/J3 and T601/J4
  courtyards, **on every layer**.
- **Mounting holes:** M2, hole clearance 1.65 mm.
- **Net tie NT1:** CELL0 (the C0 sense) meets V− only at NT1 next to J1 pin 1. DRC should
  flag any other CELL0/V− contact.
- Track classes: cell sense 0.25 mm, balance 0.3 mm, supply 0.4 mm, isoSPI 0.25 mm. A few
  tracks are 0.2 mm where they pass 0.65 mm gaps (CELL taps between R2 parts, CELL0 past NT1).

## Lean layout as routed (summary; details in the design basis "Variants" bullets)

- J1/J5 (cell plugs, JST PH 10-pin) on the top edge, J2 (NTC plug) standing on the left edge,
  J3/J4 (isoSPI JST GH) top right with transformers T501/T601 under them and the
  termination rows under those. U1 sits centre-right at x 36, 1.3 mm above the bottom edge.
  Q301 (FZT853 SOT-223, regulator NPN) stands bottom right with a VCOLL zone on all four
  layers (about 119 mm² per layer, 31 stitching vias).
- Layers: **F.Cu** most signals; **In1** S11–S18 balance lines, port A isoSPI pair, DRIVE,
  VREG pin-55 hop, VREF2 to the NTC parts, GPIO2, one V− link; **In2** U1's bottom pins
  (S1, S2, C0_F, C1_F, GPIO1–4), CELL18 to R302, port A centre tap; **B.Cu** the V− pour
  (whole board minus the isoSPI area), one IPB hop, the VCOLL zone.
- Copper chosen: 1 oz outer, 0.5 oz inner (JLC standard 4-layer). No stackup section in
  the board file yet.
- Single-sided assembly: every part on the front.

## Concerns already known (judge them; don't just repeat them)

1. **C0 sense line** (C0_F) runs about 48 mm on In2 beside S1 (cell 1's balance line).
   Measurement error or noise on cell 1?
2. **isoSPI port A chip-side pair** is 26.3 mm (IPA) and 32.9 mm (IMA, including branches),
   on In1 under port B's termination parts. The design basis quotes about 2 cm from datasheet
   p. 86. Port B is 17.7 / 20.4 mm. Is that a real link risk? Would swapping the ports help?
3. **V− is a back-layer pour, not a star.** The placement checklist asked for a V− star from
   U1's exposed pad (caps return there, balance current kept out of it). Check how the balance
   return of cell 1 and the supply/decoupling currents actually flow now.
4. **Q301 heat:** about 1.05 W in a SOT-223 on ~119 mm² per layer, where its datasheet rating
   assumes 52 × 52 mm of 2 oz copper. R302 takes ~0.5 W. VREG runs under Q301's body and cuts
   pin 2 off the tab on the front (a via joins it on the inner layers).
5. **Die heat / balance current:** 18 channels at ~31 mA through the internal switches
   (4–10 Ω). The design basis "Open items" still lists the die thermal budget as open (written
   for Guard's 89 mA).
6. **Clearances at exactly the minimum** (they pass DRC): the V− via between R502 and C501,
   the GPIO2 track through C702's pads, several 0.2 mm tap tracks, the In1 V− link at 0.21 mm
   beside the IPB via and port A's IMA lane, IMB 0.615 mm from Q301's tab (needs 0.6).
7. **Silkscreen** has never been cleaned up (153 silk violations).
8. **No Lean BOM, pick-and-place file or Gerbers** exist yet; `slave-18s/bom.csv` is Guard's.
   FZT853 stock was thin (264) when chosen.
9. Not yet confirmed: J1/J5/J2 pin order against the real Funwheel harness, isoSPI polarity
   against the master, and whether soldering a slave flat onto a carrier through its plug holes
   is sound.

## What to review (in this order)

1. **Run the checks above.** Report any difference from the expected result.
2. **Schematic against the datasheet** (Guard is the source; check the generated Lean netlist
   too). Pin map of U1 (symbol `slave-18s/symbols/ADBMS1818.kicad_sym`), the regulator
   (Q301, R301/C301 V+ filter, R302/C302, C303), VREF1/VREF2/IBIAS/ICMP values, ISOMD/DTEN/WDT
   strapping, GPIO5–9 tied to V−, NTC dividers, isoSPI termination, the net tie. Is anything
   wired wrong, or a value wrong for an 18S stack at 75.6 V? Are the deviations justified?
3. **HV safety in copper.** Do the bank rules really cover every pair of nets that can be
   more than 30 V apart, including vias, zones and inner layers? Are there spots where
   adjacent copper differs by more than its rule assumes (an S pin while balancing, CELL9
   shared by both plugs, J1 pin 1 next to J5 pin 10, VCOLL/VP_F next to bank 0)? Hole and
   board-edge distances?
4. **Signal integrity and measurement.** Concerns 1–3 above, plus anything else: Kelvin
   sensing of each Cn_F at the right point, balance current sharing a path with a sense line,
   isoSPI pairs routed as pairs, ground return of the isoSPI centre-tap caps, VREG/VREF
   decoupling loop lengths.
5. **Thermal.** Q301, R302, the balance resistors (0.12 W each in 1206) and U1's die at 18
   channels balancing. Is anything likely to exceed its rating in a closed pack at 40 °C?
6. **Manufacturability (JLCPCB 4-layer, standard assembly).** Vias 0.5/0.2 mm, track/space
   0.2 mm, the 0.5 mm-pitch QFP with 16 thermal vias in its exposed pad, 0402 parts, via
   placement relative to pads (any via-in-pad?), acid traps or slivers in the pours, silkscreen
   on pads. Parts availability for the Lean BOM (LCSC numbers are in the schematic fields).
7. **Mechanical.** Board 70 × 32 mm with M2 holes in the corners. Connector heights against
   the 10 mm slot, plug access, standing Q301 and the 2512 R302.
8. **Docs and repo hygiene.** Where do the docs contradict the board or each other? Which
   files or sections are obsolete? This list feeds a later cleanup prompt. Don't fix anything.

## Known stale text (don't report these one by one; say if there's more)

- `README.md` says Lean is "70 × 50 mm so far (try 2, placed, not routed)" with bare test
  pads on the back. Lean is now 70 × 32, routed, with no test points.
- The status paragraph at the top of `docs/slave-18s-design-basis.md` is from 2026-11-06
  ("Placement, outline and routing are not done"). Its "Open items" list still has "Board
  outline (placeholder)" and "Final placement, then routing" unticked, and the placement
  checklist is mostly unticked.
- `docs/slave-18s-lean-layout-plan.md` says "try 2, not routed" and gives rules for a
  2-layer board.
- Untracked local files you may see: `slave-18s-lean/report.txt` (an old KiCad F8 report),
  `slave-18s-lean/*.boxes.json` (dashboard annotations, empty), `.claude/`.

## Rules for you

- Never publish, quote or copy anything from `_reference/racc/`, `_reference/datasheets/` or
  `_reference/firmware/`. You may use what the tracked docs already say about Racc's board.
- Never invent pin numbers or datasheet values. Cite the datasheet page and figure, or say
  you could not check it.
- Don't count as problems: "symbol doesn't match library" and "library not in configuration"
  ERC warnings (cosmetic), `via_dangling` in DRC run without `--refill-zones`, or KiCad's CRLF
  line endings.

## Report format

Start with a three-line verdict: can Lean be ordered as it is, and if not, what blocks it.

Then the findings, **most severe first**. For each one:

- **Severity:** Blocker (board won't work, unsafe, or fab rejects it) / Major (works badly
  or risky; fix before ordering) / Minor (fix when convenient) / Docs.
- **Where:** file and line, reference designators, net names, board coordinates in mm.
- **Evidence:** the command and its output, the datasheet page, or the measurement. Say
  plainly if it's a judgement and not checked.
- **Why it matters,** in one or two sentences.
- **Suggested fix,** and what it would cost (board size, layers, parts, routing redone).

Then: (a) the known concerns 1–9 with your verdict on each (real problem / acceptable /
can't tell, and why); (b) the stale-docs and junk-file list for the cleanup pass; (c) what you
could not check.
