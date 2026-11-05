# Working in testing-BMS-designs

Read README.md and `docs/slave-18s-design-basis.md` before design work.

- Current target: ADBMS1818 **18S** slave module. The master is out of scope for now.
- Baseline circuit: ADBMS1818 datasheet Figure 112 (typical application). Write every
  deviation into the design basis with a reason.
- Keep the extra isoSPI filtering (split termination + centre-tap caps) from Racc's
  reference. It is there for motor noise, even though the datasheet figure lacks it.
- Never invent pin numbers. Build symbols and footprints from the manufacturer's pin
  table and cross-check against the exported netlist.
- `_reference/racc/` is private. Never publish it, copy it into `site/`, or remove it
  from `.gitignore`.
- Keep the Board Boxes toolbars and features intact when changing the dashboard.
- Keep documentation commits separate from schematic and PCB commits.

## KiCad MCP (mixelpixx KiCAD-MCP-Server at C:\Users\quinn\KiCAD-MCP-Server)

Configured for this repo in `.mcp.json`. Tips from its docs (HEADLESS_AUTHORING, KNOWN_ISSUES):

- **kicad-cli is ground truth.** When a skip-based MCP tool disagrees with ERC, a
  render or the netlist, believe `kicad-cli`.
- **Per-sheet recipe:** `create_schematic` -> `batch_add_and_connect` (net names, symbol
  origins on a 2.54 mm grid, parts ~12.7 mm apart) -> `batch_add_no_connects` ->
  `run_erc` -> export SVG and actually look at it.
- **Done means:** 0 ERC errors with warnings triaged, the render eyeballed, and the
  netlist checked for any pin you are unsure about. Never trust "connected N pins" alone.
- **Grid:** the connection grid is 1.27 mm. One off-grid origin can break junctions on the
  whole sheet. Use `lint_offgrid` (fix sub-0.5 mm offenders); never snap inside `lib_symbols`.
- **ERC:** run on the root sheet for hierarchical designs. Report coordinates are mm/100.
  "Symbol doesn't match library" and "library not in configuration" are cosmetic.
- **Power flags:** exactly one driver per power net design-wide. Rails fed only by
  connectors or passives need one `PWR_FLAG`.
- **Vendor symbols:** flat SnapEDA/SamacSys symbols break skip-based tools; run
  `repair_flat_symbols` first. Vendor output pins are often typed `passive`.
- **Deleting a wired part leaves its labels behind.** Clean them up.
- **SWIG backend:** KiCad's UI will not show MCP edits until you reload (File > Revert).
  Zone fill via SWIG can segfault; let KiCad fill zones when the board is opened.
- **`.kicad_pro` net classes:** edit by JSON read-modify-write, not through the pcbnew model.
- JLCPCB API keys are not set; the local parts DB in `~/.kicad-mcp/data` still works.
