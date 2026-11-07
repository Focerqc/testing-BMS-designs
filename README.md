# Testing BMS designs

Experimental battery-management hardware, built in public. The first design is an
**18S cell-monitoring slave module** based on the Analog Devices **ADBMS1818**,
talking to a separate master over isoSPI.

> Engineering drafts. Nothing here is validated for manufacture or use on a real pack.

## Layout

| Path | What it is |
|---|---|
| `slave-18s/` | **18S Guard**: KiCad 10 project for the ADBMS1818 18S slave with hot-plug protection |
| `slave-18s-lean/` | **18S Lean**: the same slave without fuses, clamps, TVS or C-pin caps; schematic generated from Guard by `_tools/kicad_sch/make_lean.py` |
| `docs/slave-18s-design-basis.md` | Values, reasoning and open items for the slave |
| `docs/slave-18s-lean-layout-plan.md` | Step-by-step placement and routing plan for the 18S Lean PCB, with the check to run after each step |
| `docs/master-ennoid-xlite.md` | The bought master (ENNOID Master-XLITE-ISC) and how the slave fits under it |
| `_tools/pcb_dashboard/` | Board Boxes: local KiCad dashboard (view, annotate, chip info, fresh 3D renders, copy placement prompts) |
| `_tools/kicad_sch/` | Schematic helpers: netlist + ERC check of the slave, label fixer, region renders (see AGENTS.md) |
| `site/` | Published GitHub Pages copy of Board Boxes plus the News page |
| `_reference/` | Reference images. `_reference/racc/`, `_reference/datasheets/` and `_reference/firmware/` are private and gitignored |

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

1. 18S slave schematic from the ADBMS1818 typical application.
2. Slave PCB, bench test with a resistor-ladder cell simulator + LTC6820/ESP32 dongle.
3. Carrier PCB taking two slaves for a plug-and-play Funwheel harness.
4. Master: bought, not designed here. ENNOID Master-XLITE-ISC (see `docs/master-ennoid-xlite.md`).
