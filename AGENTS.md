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

### What went wrong while wiring the slave (2026-11-05, MCP v2.7.0)

- **Eeschema may have the file open.** If `~<name>.kicad_sch.lck` exists, Eeschema has it
  open. It won't see edits made on disk, and saving from it overwrites them. Tell the user
  before editing; they reload with File > Revert.
- **`batch_connect` labels face into the part.** `get_pin_angle` already returns the
  outward angle, and `batch_connect` flips it again (`python/commands/schematic_batch.py`,
  the `{0: 180, 90: 270, ...}` map). The connections are right, but the text runs across
  the part. Run `_tools/kicad_sch/orient_labels.py` after every batch.
- **`connect_to_net`** draws its 2.54 mm stub in the right direction but always places the
  label at angle 0 (text to the right). Read in the source; not used here.
- **30 s timeout, but the work keeps going.** Node abandons `batch_connect` after 30 s,
  while the Python worker keeps rewriting the whole file once per label (about 1 s each on
  a 300 kB sheet; the file is briefly 0 bytes between writes). Keep batches to about 15
  labels. After a timeout, leave the file alone until it has been unchanged for 30 s, then
  count the labels.
- **Every MCP edit rewrites the whole file** in its own format, with float noise like
  `78.74000000000001`. Run `kicad-cli sch upgrade --force <sch>` after each MCP batch. You
  get KiCad's own format (the netlist was checked identical), small diffs, and a load test
  for free: it fails if the file is broken.
- **`add_schematic_component` flips field positions in y.** A new PWR_FLAG showed its
  `#FLG` reference, with both fields below the flag. Hide the reference and put Value
  3.81 mm above the pin, as KiCad's library does.
- **`move_schematic_component` leaves labels behind** at the old pin points, and they
  float. Use `_tools/kicad_sch/shift_group.py`, or delete the labels, move, and reconnect.
- **Raw newlines break text items.** Inside a KiCad string, write `\n` (backslash-n). A
  real line break makes the file fail to load.
- **ERC facts:** passive pins satisfy `input` pins. `power_in` needs a `power_out` pin or a
  PWR_FLAG. PWR_FLAG pins don't appear in the netlist, so check them with ERC
  (`power_pin_not_driven`). Run `kicad-cli sch erc --severity-all`; clean prints "Found 0
  violations". A copy outside the project folder adds `lib_symbol_issues` and
  `footprint_link_issues` warnings because its libraries aren't found. That's the copy,
  not the design.
- **Readability:** on vertical parts the labels are vertical text. Check the render for
  labels in the same column running end to end (`S1` over `CELL10` read as one string)
  and for labels running into heading text.
- `lint_offgrid` and `list_floating_labels` worked and agreed with kicad-cli.

### Helper scripts (`_tools/kicad_sch/`)

| Script | Use |
|---|---|
| `check_slave18s.py` | kicad-cli netlist + ERC check of the slave against its wiring table. Exit 0 = pass. Run after every schematic edit (`--blocks 1 2` for part of it, `--erc` to list violations) |
| `orient_labels.py` | Writes the file: turns pin labels to face outward and rounds coordinates (`--dry` to preview) |
| `shift_group.py DX DY REF...` | Writes the file: moves parts together with their labels and no-connect flags |
| `render_sch.py OUT.png --region X0 Y0 X1 Y1` | PNG of the sheet or a region (sheet mm) via kicad-cli PDF + PyMuPDF |
| `kisch.py --pins REGEX` | Lists parts, pin end points (mm) and which way each pin faces |

Wiring recipe that worked: back up the sheet -> MCP `batch_connect` (about 15 labels) ->
if it timed out, wait for the file to settle -> `kicad-cli sch upgrade --force` ->
`orient_labels.py` -> `upgrade --force` again -> `check_slave18s.py` -> render the region
and look -> `lint_offgrid` + `list_floating_labels` -> commit the schematic alone.
