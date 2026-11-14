# Testing BMS designs

Experimental battery-management hardware, built in public. The first design is an
**18S cell-monitoring slave module** based on the Analog Devices **ADBMS1818**,
talking to a separate, bought master over isoSPI.

> Engineering drafts. Nothing here is validated for manufacture or use on a real pack.

## Status (2026-11-13)

| | **18S Guard** (`slave-18s/`) | **18S Lean** (`slave-18s-lean/`) |
|---|---|---|
| Purpose | Hot-plug harnesses, unknown packs, bench work | One known 18S pack, harness plugged in once |
| Schematic | Complete, ERC 0 / 0 | Generated from Guard, ERC 0 / 0 |
| PCB | 120 × 70 mm placeholder, parts grouped, **not routed** | **70 × 32 mm, 4 layers, fully routed**, every part on the front |
| Ready to order | No | **No.** The isoSPI area is being re-planned (see below) |

Lean is the board being worked on. Guard is its source: Lean's schematic is generated from
Guard by `_tools/kicad_sch/make_lean.py` and is never edited by hand.

### Lean at a glance

- 77 footprints, 88 nets, single-sided assembly, four M2 holes.
- Cell plugs: JST PH, **10 + 9 pins**. J1 carries C0–C9 and J5 carries C10–C18, so C9 comes in
  on one wire and the two plugs can be told apart.
- Per cell: a 10 Ω 0402 series resistor and a 120 Ω 1206 balance resistor (about 31 mA and
  0.12 W at 4.2 V) through the chip's internal switches.
- Regulator: FZT853 (SOT-223) driven by the chip, with a 1 kΩ 1 W collector resistor that
  takes part of the heat off the transistor.
- isoSPI: two Bourns SM91502AL transformers, split 2 × 51 Ω termination with 10 nF
  centre-tap capacitors, JST GH 2-pin plugs.
- No fuses, clamps, TVS or C-pin capacitors. Those are Guard's.

Its checks on this branch: netlist 239 pins with 0 problems, PCB parity pass, design rules
loaded, and zone-filled DRC with 0 errors, 0 unconnected items and 153 silkscreen warnings.

## What we have learned so far

### 1. A clean DRC does not make an isoSPI layout right

The ADBMS1818 datasheet (Rev. B, p. 86) asks for two things that DRC cannot see: no ground
plane under or between the transformer and its plug, and **no trace crossing an isoSPI line**
unless a ground plane on an inner layer separates them. Lean meets the first with keep-out
rules. For the second we wrote `_tools/kicad_sch/isospi_shield_check.py`.

- The first version of that check reported 6 crossings. It looked only at the transformer
  centre-tap and termination nets and never treated the chip-side pairs (IPA/IMA, IPB/IMB) as
  isoSPI lines. With each port grouped properly it finds **20**: 12 where port A crosses
  port B, and 8 where the top-of-stack supply track (CELL18) crosses either port.
  The lesson: check a checker against the circuit before trusting its number.
- **Rerouting cannot remove them.** Both ports sit side by side in one corner. Port A's pins
  are below port B's on the chip and its transformer is the far one, so port A has to get
  past port B. Port B fills the whole height from its plug at the board edge down to the
  regulator copper, and the rules keep other tracks out from under its transformer. The best
  a reroute can do is 10 crossings.
- The top-of-stack supply has the same problem: it starts above both ports and ends at the
  regulator below them.

### 2. Put the two isoSPI ports at opposite ends

We compared three other slave boards of this kind. Every one of them puts its two isoSPI ports
at **opposite ends of the board**, each plug with its transformer right beside it. Lean is the
only one that groups them. Splitting them means:

- each port runs from its pins to its own end, so the ports never meet;
- the daisy-chain cables leave from opposite ends instead of crossing over the board;
- the regulator and the top-of-stack supply can be kept clear of both ports.

**Planned next step:** a new Lean floorplan with one port at each end. It moves parts, so it
is tried on a scratch copy first.

### 3. What turned 120 × 70 mm into 70 × 32 mm

- Four copper layers instead of two.
- Small series resistors (the 10 Ω parts carry almost no current) and 120 Ω 1206 balance
  resistors instead of 33 Ω 2512.
- Smaller isoSPI transformers, GH plugs, M2 holes and no test points.
- Leaving out the hot-plug protection, which is the Guard/Lean split.
- Routing planned as lanes before any track is drawn, then written by script from the pad
  positions (`lean_place.py`, `lean_route.py`), so a placement change can be routed and
  checked again in minutes.

### 4. The regulator is a heat question, not a fit question

At 75.6 V the linear regulator dissipates about 1.55 W at 22 mA and 2.5 W at 35 mA, whatever
the package. The 1 kΩ collector resistor only moves part of that off the transistor (about
0.48 W of the 1.55 W). Whether the board stays cool enough is still open. It needs the
master's real duty cycle or a measurement.

### 5. Working method

- One source schematic and generated variants. Part swaps for Lean live in one table.
- `kicad-cli` is the ground truth for netlist, ERC and DRC. Every schematic or PCB change is
  followed by the same scripted checks (below).
- Size and placement changes are tried on a scratch copy before the real board.
- The tool-by-tool lessons are in [AGENTS.md](AGENTS.md).

## Open before Lean can be ordered

- [ ] isoSPI floorplan with the ports at opposite ends, then 0 crossings in the check.
- [ ] Regulator thermal acceptance (see 4).
- [ ] The assembler's acceptance of the open 0.2 mm vias in the chip's exposed pad.
- [ ] Silkscreen cleanup (153 warnings).
- [ ] Harness: match the plug pin order to the pack's tap and thermistor wiring. Seen from
      above with the cell plugs along the top edge, pin 1 of both is at the left end.
- [ ] Bench test with a cell simulator and one master. Hot-plugging is not qualified on Lean.

The full list, with reasons and dates, is in
[docs/slave-18s-design-basis.md](docs/slave-18s-design-basis.md).

## Checks

```
"C:\Program Files\KiCad\10.0\bin\python.exe" _tools/kicad_sch/lean_route.py --dry
python _tools/kicad_sch/check_slave18s.py --variant lean
python _tools/kicad_sch/check_pcb_parity.py --variant lean
python _tools/kicad_sch/make_rules.py --variant lean --check
python _tools/kicad_sch/isospi_shield_check.py
```

Then run `kicad-cli pcb drc --severity-all --refill-zones` on the board.

## Layout of this repository

| Path | What it is |
|---|---|
| `slave-18s/` | **18S Guard**: KiCad 10 project with hot-plug protection (fuses, clamps, TVS, C-pin caps, test points) |
| `slave-18s-lean/` | **18S Lean**: the same slave without them, 70 × 32 mm, 4 layers. Schematic generated by `make_lean.py`; placement and routing written by `lean_place.py` and `lean_route.py` |
| `docs/slave-18s-design-basis.md` | Values, reasoning, deviations from the datasheet circuit and open items |
| `docs/slave-18s-lean-layout-plan.md` | Placement and routing plan for Lean, with the check to run after each step |
| `docs/master-ennoid-xlite.md` | The bought master and how the slave fits under it |
| `_tools/kicad_sch/` | Checks, design-rule generator, Lean generator, placement and routing scripts (table in AGENTS.md) |
| `_tools/pcb_dashboard/` | Board Boxes: local KiCad dashboard (top and bottom view, annotate, chip info, fresh 3D renders) |
| `site/` | Published GitHub Pages copy of Board Boxes plus the News page |
| `_reference/` | Datasheets and reference material. The private parts are gitignored |

## Dashboards

- **Local:** double-click `Start Dashboards.cmd` (Python with `requirements.txt`, KiCad 10).
  Opens http://localhost:5180/.
- **Hosted:** https://focerqc.github.io/testing-BMS-designs/ (News at `news.html`).

Refresh the hosted copy:

```
python _tools/pcb_dashboard/export_site.py
node _tools/pcb_dashboard/check_hosted.cjs
```

Then push `site/` to `main`; `.github/workflows/pages.yml` publishes it.

## Roadmap

1. ~~18S slave schematic from the ADBMS1818 typical application.~~ Done.
2. Slave PCB: Lean is routed. Redo its isoSPI floorplan, then order and bench test with a
   resistor-ladder cell simulator and an LTC6820/ESP32 dongle.
3. Carrier PCB taking two slaves (target slot 156.5 × 37 × 10 mm) for a plug-and-play harness.
4. Master: bought, not designed here (see `docs/master-ennoid-xlite.md`).
