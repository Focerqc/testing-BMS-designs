# ADBMS1818 18S slave: design basis

Status: **schematic complete for a first bench board, PCB roughly grouped, 2026-11-06.**
Every part is on the root sheet with Value, Footprint, LCSC and MPN filled in, grouped by
function, and connected with net labels (see "Schematic nets"). kicad-cli ERC: 0 errors, 0
warnings. Hot-plug protection, test points and mounting holes were added on 2026-11-06 (see
"Protection and test points"). Net classes and HV clearance rules are in the project (see
"Net classes and clearance rules"). Placement, outline and routing are not done. The JLC BOM
is `slave-18s/bom.csv`.

## Scope

- One ADBMS1818 monitoring up to 18 series Li-ion cells (4.2 V max each, 75.6 V stack).
- isoSPI daisy chain: port A in, port B out (ISOMD tied to VREG).
- Passive balancing through the internal S-pin switches.
- Thermistor inputs on GPIOs.
- No power switching and no charge control. Those live in the master, a bought ENNOID
  Master-XLITE-ISC (decision 2026-11-06, see `docs/master-ennoid-xlite.md`). No XT30s on
  the slave.

## The chip (from the datasheet, Rev. B)

- **Package:** 64-lead LQFP with exposed pad, 10 × 10 mm, 0.5 mm pitch. Two outlines exist:
  05-08-1982 (EP 5.74 mm) and SW-64-2 (EP 5.50 mm). The stocked JLC part
  (ADBMS1818ASWAZ-RL) is SW-64-2. Footprint: stock KiCad
  `Package_QFP:LQFP-64-1EP_10x10mm_P0.5mm_EP5x5mm_ThermalVias`. Its 5 × 5 mm pad sits
  inside both EP sizes. The 6.5 mm variant would overhang the EP.
- **EP is pin 65 = V−.** It must be soldered, and it must join pins 59/60 (V−) outside the IC.
- **Cell pins run downward:** pin 2 = C18, pin 3 = S18, … pin 36 = C1, pin 37 = S1,
  pin 38 = C0. In general Cn = pin 38 − 2n and Sn = pin 39 − 2n.
- Right side: 39–47 GPIO1–9, 48 VREG, 49 DRIVE, 50 VREF2, 51 VREF1, 52 DTEN,
  53 SDI (NC in isoSPI mode), 54 SDO (NC), 55 ISOMD, 56 WDT, 57 IBIAS, 58 ICMP,
  59/60 V−, 61 IMA, 62 IPA, 63 IMB, 64 IPB.
- Symbol `slave-18s/symbols/ADBMS1818.kicad_sym` was built from Figure 2 and Table 14.
  The exported netlist was checked pin by pin against that map (65 pins, 0 mismatches).
  No eval board files were supplied, so there was no second source to cross-check.
- Discharge switch on-resistance: 4 Ω typ, 10 Ω max (V_CELL = 3.6 V). Thermal shutdown
  about 150 °C (it turns the discharge switches off).
- VREG current: 15 mA typ / 16.5 mA max in measure mode, plus 4.0–6.5 mA for isoSPI ready
  (ISOMD = VREG). The datasheet says the peak approaches 35 mA when converting and
  communicating at once.

## Baseline: datasheet Figure 112 (typical application)

| Block | Value | Note |
|---|---|---|
| C-pin series resistor | 10 Ω | Per input, C0–C18 (19) |
| C-pin filter cap | 100 nF **to V−** | Per Cn, C1–C18 (18), after the 10 Ω. Grounded-cap filter, so each cap sees up to the full stack: **100 V rated** |
| S-pin balance resistor | 33 Ω | From the cell node (before the 10 Ω) to Sn |
| V+ filter | 100 Ω + 100 nF (100 V) V+ to V− | The earlier note said 10 nF. Figure 112 shows 100 nF |
| DRIVE regulator | NPN, 100 Ω from top of stack to collector, **100 nF** (100 V) at the collector, 1 µF at VREG (emitter) | Figure 112 shows 10 nF. We use the datasheet text's 100 Ω / 100 nF RC (deviation 6) |
| VREF1 / VREF2 | 1 µF each | |
| isoSPI termination | 100 Ω | Split 2 × 51 Ω with centre-tap caps (below) |
| IBIAS / ICMP | IBIAS–1 kΩ–ICMP–1 kΩ–V− | |
| ISOMD | to VREG | isoSPI mode |

Correction: the earlier version of this note listed a "C-to-S filter cap". Figure 112 puts
the 100 nF from each Cn to **V−**, not to S. That changes the voltage rating from cell-level
to stack-level (100 V parts).

## Deviations from Figure 112

1. **isoSPI filtering (Racc's design):** termination split into 2 × 51 Ω with 10 nF from the
   centre point to V−, plus 10 nF on the transformer chip-side centre tap. Keeps isoSPI
   working while the motor runs. This is not really a deviation from the datasheet, only
   from the simplified Figure 112. The isoSPI text (p. 81) calls the plain 100 Ω of Figure 103
   "inadequate for most designs" and says RM must be split and bypassed. Figure 104(B) is
   exactly this circuit: 2 × 51 Ω, 10 nF midpoint to V−, 10 nF chip-side CT to V−, plus a
   100 µH CMC (HM2113ZNL has the choke built in). **Don't go above 10 nF:** the datasheet
   says larger CT caps can keep the isoSPI common mode from settling.
2. **Regulator NPN in a big package.** Dissipation ≈ (V_stack − I·100 Ω − 5 V) × I_reg. At
   75.6 V and 20–23 mA (measure + isoSPI) that's about 1.4–1.6 W, with peaks near 35 mA.
   FZT853 (SOT-223, 3 W on 52 × 52 mm of 2 oz copper) needs generous collector copper.
3. **Thermistors:** 100 kΩ pull-up to VREF2, 100 kΩ NTC, 100 nF on the GPIO (Racc's
   arrangement). Three cell NTC inputs on GPIO1–3 and one onboard 0603 NTC on GPIO4.
4. **Balance resistor 33 Ω in 2512 (1 W).** See sizing. Two 68 Ω 1206s were the
   alternative, but C17976 (68 Ω 1206) is an Extended part too, and each 1206 would run at
   about 82 % of its 0.25 W rating on a board that heats up while balancing.
5. **isoSPI transformer HM2113ZNL instead of HX1188FNL.** See the transformer section.
6. **Collector cap 100 nF instead of Figure 112's 10 nF.** The datasheet text (Simple Linear
   Regulator) recommends a 100 Ω, 100 nF RC on the collector to protect the NPN from transients.
   It's also the same Basic part as the filter caps (C28233), so there's one fewer Extended line.
7. **Tap fuses F100–F118 and split supply fuses F119/F120 (2026-11-06).** Figure 112 has none.
   Source: ADI AN-2093 (ADBMS1818 slave module) Fig. 11. See "Protection and test points".
8. **Zener clamps D101–D118 between neighbouring C pins (2026-11-06).** Figure 112 has none.
   Source: abs max Table 11 (p. 11, 8 V between C pins), AN-2093 Fig. 12.
9. **TVS D301 across the stack after F119 (2026-11-06).** Source: V+ abs max 112.5 V
   (Table 11), FZT853 VCEO 100 V, AN-2093 D1401.
10. **R100–R118 in 1206 instead of 0603 (2026-11-06).** Figure 99 (p. 75) shows the balance
    current of cell n returning through the C(n−1) series resistor, so each 10 Ω carries
    about 89 mA (≈ 79 mW, 79 % of an 0603's 0.1 W). The 1206 is rated 0.25 W.
11. **Test points and mounting holes (2026-11-06).** Not part of the circuit; bench access.
12. **isoSPI connectors J3/J4 = JST GH 2P, with JST PH 2P alternates J6/J7 (DNP) (2026-11-06).**
    Figure 112 shows no connector. The bought ENNOID master and ENNOID's slaves use GH 2P for
    isoSPI, so the master's cable plugs straight in. J6/J7 are PH footprints wired in parallel
    and left unfitted, so a PH header or two bare wires can be soldered instead. See
    "Connectors".
13. **GPIO5–GPIO9 tied to V− (2026-11-06).** Figure 112 leaves them open. The ENNOID firmware
    never turns their internal pull-downs on, so they would float. See "Configuration and unused
    pins".

## Balance resistor sizing

Uses the datasheet switch resistance (4 Ω typ, 10 Ω max). **Corrected 2026-11-06:** the first
table ignored the 10 Ω filter resistor. Figure 99 (p. 75) shows the discharge path as
CELLn → R2nn → Sn → internal switch → C(n−1) pin → R1(n−1) → CELL(n−1), so the loop is
R_S + R_switch + 10 Ω. The tap fuses add roughly 2 × 0.7 Ω more (cold resistance, not yet
checked against the Littelfuse sheet), which lowers the current slightly; it is left out here.

| R_S | I at 4.2 V (4 Ω switch) | I at 4.2 V (10 Ω switch) | P in R_S at 4.2 V |
|---|---|---|---|
| 120 Ω (Racc's board) | ~31 mA | ~30 mA | 0.12 W |
| 47 Ω | ~69 mA | ~63 mA | 0.22 W |
| **33 Ω (Fig. 112)** | **~89 mA** | **~79 mA** | **0.26 W** |

- 0.26 W in a 1 W 2512 is about 26 % loading.
- Each 10 Ω series resistor carries the same current: about 79 mW, hence 1206 (deviation 10).
- All 18 balancing at once is about 6.7 W on the board (18 × 4.2 V × 89 mA). Firmware should
  balance odd and even cells alternately, or the layout needs copper for heat spreading.
- Firmware: keep DCP = 0 so balancing pauses during conversions (otherwise C(n−1) reads about
  0.9 V off through the 10 Ω), and limit balancing to ≤ 80 mA per cell when the die is above
  85 °C (p. 75). Read the die temperature (ITMP) while balancing.
- The track widths (see "Track widths") were set with the old 114 mA figure, the safe side.

## isoSPI transformer

The datasheet (Table 74) rates HX1188FNL at **60 V working (estimate)**. Adjacent 18S
modules sit about 76 V apart, so that is not enough. Chosen part: **Pulse HM2113ZNL**
(one per port, T501 = port A, T601 = port B).

- From the Pulse datasheet (BM101.C, 11/22): 1:1, 150 µH min, 0.50 µH max leakage,
  choke fitted, 4300 Vrms / 60 s, **1000 VDC working**, −40 to +125 °C, AEC-Q200. Meets the
  ADI limits (> 60 µH primary, < 2.5 µH leakage).
- Pinout: chip (PHY) winding 1 – 2 (CT) – 3; line winding with CMC 6 – 5 (CT) – 4.
  The 10 nF chip-side CT cap goes on pin 2.
- JLC lists it as "SMD-12P". The Pulse drawing shows 6 pads, which is what the footprint
  uses.
- Footprint `slave-18s/footprints.pretty/Pulse_HM2113ZNL.kicad_mod` was drawn from the
  Pulse land pattern: 6 × 1.02 mm pads, 2.54 mm pitch, rows 12.40 mm inner / 16.18 mm outer.
  KiCad has no stock footprint for it.
- **Pad numbering checked 2026-11-05** against BM101.C p. 2 (mechanical drawing and HM2113ZNL
  schematic), with the drawing rendered next to the footprint. The drawing marks pin 1 with a
  dot and a chamfered body corner but prints no numbers. Turned 90° CW to match the
  footprint, the dot lands at pad 1 (top left, beside the silk dot). Numbering
  counter-clockwise from the dot gives 1-2-3 down the chip-side row and 4-5-6 up the line-side
  row, the same as the schematic page (1-2-3 on the PHY winding, 6-5-4 on the choked line
  winding). Pad size, pitch and row spans match the land pattern to 0.01 mm. Remaining
  assumption: counter-clockwise numbering is the industry convention, not printed on the
  drawing. Check one real part's marking against pad 1 at first assembly.

## Parts and JLC numbers

All picks were checked on jlcpcb.com/partdetail on 2026-11-05 (Basic/Extended flag and stock).

| Ref | Part | Footprint | LCSC | Type | Stock |
|---|---|---|---|---|---|
| U1 | ADBMS1818ASWAZ-RL | LQFP-64-1EP 10×10, EP5×5 | C5372802 | Extended | 12,496 |
| R100–R118 | 10 Ω 1 % 250 mW (1206W4F100JT5E) | 1206 | C17903 | Basic | 985,965 |
| C101–C118, C301, C302 | 100 nF 100 V X7R (filters, V+, collector) | 0805 | C28233 | Basic | 3.25 M |
| R201–R218 | 33 Ω 1 % 1 W | 2512 | C53728 | Extended | 49,062 |
| R301 | 100 Ω 1 % (V+) | 0603 | C22775 | Basic | 8.6 M |
| R302 | 100 Ω 1 % 150 V (collector) | 0805 | C17408 | Basic | 7.4 M |
| Q301 | FZT853TA, NPN 100 V 6 A 3 W | SOT-223 | C435890 | Extended | 264 |
| C303–C305 | 1 µF 50 V X5R (VREG, VREF1, VREF2) | 0603 | C15849 | Basic | 11.9 M |
| R401, R402 | 1 kΩ 1 % | 0603 | C21190 | Basic | 28 M |
| T501, T601 | Pulse HM2113ZNLT | Pulse_HM2113ZNL | C5730533 | Extended | 6,533 |
| R501, R502, R601, R602 | 51 Ω 1 % | 0603 | C23197 | Basic | 2.0 M |
| C501, C502, C601, C602 | 10 nF 50 V X7R | 0603 | C57112 | Basic | 5.3 M |
| R701–R704 | 100 kΩ 1 % (NTC pull-ups) | 0603 | C25803 | Basic | 16.6 M |
| C701–C704 | 100 nF 50 V X7R (GPIO) | 0603 | C14663 | Basic | 36.6 M |
| TH701 | Murata NCP18WF104F12RB, 100 k 1 % B 4250 K | 0603 | C71280 | Extended | 115 k |
| J1, J5 | JST B10B-PH-K-S(LF)(SN), 1×10 2 mm, 100 V 2 A (cell taps) | JST_PH_B10B-PH-K_1x10_P2.00mm_Vertical | C158038 | Extended | 25,205 |
| J2 | JST B6B-PH-K-S(LF)(SN), 1×6 (cell NTCs) | JST_PH_B6B-PH-K_1x06_P2.00mm_Vertical | C131342 | Extended | 32,477 |
| J3, J4 | JST SM02B-GHS-TB(LF)(SN), GH 1×2 1.25 mm, SMD side entry, 50 V 1 A (isoSPI A / B) | JST_GH_SM02B-GHS-TB_1x02-1MP_P1.25mm_Horizontal | C189893 | Extended | ~130 k (LCSC) |
| J6, J7 | JST B2B-PH-K-S(LF)(SN), PH 1×2, **DNP** (alternate to J3/J4) | JST_PH_B2B-PH-K_1x02_P2.00mm_Vertical | C131337 | Extended | not in the JLC BOM |
| F100–F120 | Littelfuse 0466.250NRHF, 250 mA 125 V DC, 50 A interrupt | Fuse_1206_3216Metric | C83557 | Extended | 50,048 |
| D101–D118 | BZT52C6V8 (CJ), 6.8 V zener 500 mW | D_SOD-123 | C2120 | Extended | 51,589 |
| D301 | SMAJ85A (Yangjie), 85 V TVS 400 W unidirectional | D_SMA | C698956 | Extended | 4,985 |
| TP1–TP10 | Keystone 5015 SMD test loop | TestPoint_Keystone_5015_Micro_Mini | C2906768 | Extended | 53,270 |
| TP11–TP14 | Bare 1.5 mm pad (no part, not in the BOM) | TestPoint_Pad_D1.5mm | — | — | — |
| H1–H4 | M3 hole, NPTH, no copper (not in the BOM) | MountingHole_3.2mm_M3 | — | — | — |

There are 12 Extended lines: U1, R201–R218, Q301, T501/T601, TH701, the two fitted JST PH
sizes (J1/J5, J2), the JST GH (J3/J4, since 2026-11-06), and (since 2026-11-06) the fuse, zener, TVS and test loop. Every capacitor is Basic.
The 2026-11-06 additions were checked on jlcpcb.com that day. The connectors are through-hole, so they need JLC's THT
assembly or hand soldering.

Why these values are safe at the voltages involved:

- The 0603 thick-film resistors are rated 75 V. Each one only sees cell-level or IR-drop
  voltages.
- The termination and CT caps (C5xx/C6xx) and the GPIO caps sit near V− (< 6 V), so
  50 V parts are fine there.

FZT853 lead order, checked 2026-11-05 against Diodes DS33175 Rev. 6-2: p. 1 "Top View
Pin-Out" shows the tab = C and the three leads E, C, B. Turned 180° to match the footprint,
the leads read B, C, E from pad 1, so KiCad `SOT-223-3_TabPin2` (pad 1 = B, pad 2 = C on the
middle lead and the tab, pad 3 = E) matches the symbol `Q_NPN_BCE` (1 = B, 2 = C, 3 = E). The
p. 6 outline gives the dimensions only, with no pin numbers.

Rejected NPN options: PBSS8110Z (0 stock), NSS1C201MZ4 (93 stock), FZT493TA (0 stock),
PZTA42 (300 V, but hFE min only 25–40; the datasheet asks for > 40 over temperature).

## Protection and test points (added 2026-11-06)

Figure 112 has no input protection, and the datasheet has no hot-plug section. It gives the
limits (Table 11, p. 11: 8 V between neighbouring C pins, 112.5 V V+ to V−) and the
internal clamps (Fig. 95, p. 72). The parts follow ADI AN-2093, the ADBMS1818 slave module
reference (read from a mirror copy; check it against analog.com before ordering).

| Item | Why | Value / part | First board? |
|---|---|---|---|
| F100–F118 | A cracked filter cap (up to 75.6 V to V−) or a slipped scope ground cannot pull pack current through the board (AN-2093 Fig. 11) | 250 mA 125 V DC 1206 | needed |
| F119, F120 | Separate supply branches, as AN-2093 does. With one fuse per tap, the chip's ≤ 35 mA × ~0.7 Ω (≈ 25 mV) would show as error on cells 1 and 18 | same fuse | needed |
| D101–D118 | J1/J5 pins mate in random order; the zener keeps each C pair under 8 V (AN-2093 Fig. 12 uses MMSZ4692T1G, C43431; BZT52C6V8 picked for stock) | 6.8 V SOD-123 | needed |
| D301 | Protects V+ (112.5 V) and the FZT853 (VCEO 100 V) from harness transients. After F119, so a shorted TVS opens the fuse | SMAJ85A: 85 V standoff, 94.4–104 V breakdown, 137 V clamp | needed |
| R100–R118 to 1206 | See deviation 10 | 10 Ω 250 mW | needed |
| TP1–TP10 | Probe loops on the low-voltage nets (AN-2093 TP1400–TP1409) | Keystone 5015 | needed |
| TP11–TP14 | Bare pads on VCOLL, C6_F, C12_F, C18_F: no exposed loop at 25–75 V | 1.5 mm pad | needed |
| H1–H4 | M3, no copper; positions set with the outline | 3.2 mm NPTH | needed |
| Reverse-polarity Schottky (AN-2093 D1400) | JST PH is keyed; only a miswired harness can reverse it | DFLS1100-7, C107674 | nice to have, not added |
| "Awake" LED on VREG (AN-2093 LD1400) | Adds about 0.1 W to Q301 | KT-0603R + 2.2 kΩ | nice to have, not added |
| isoSPI connector ESD | Not called for by the datasheet (Fig. 104, p. 81) or the HM2113ZNL sheet; termination, CT cap and choke are the protection | — | not needed |

Footprint pad numbers were checked against the KiCad 10 stock footprints and symbols:
D_SOD-123 and D_SMA pad 1 = cathode = `D_Zener` pin 1 (K); Fuse_1206 pads 1/2; both test-point
footprints pad 1 = `TestPoint` pin 1. D301 uses `D_Zener` because KiCad's `D_TVS` is
bidirectional.

Cost: four new Extended lines (about $3 setup each per order) and about $5.40 of parts per
board.

## Configuration and unused pins

Source: Fig. 2 and Table 14, plus the Watchdog and Discharge Timer section (Table 33).

| Pin | Net | Reason |
|---|---|---|
| 52 DTEN | **V−** | Disables the discharge timer. When the master or the isoSPI link is lost, the 2 s watchdog then resets the S control registers and turns every balance switch off. With DTEN = VREG the switches would keep running for up to 120 min with no host watching, which is a bad default while the 18 × ~110 mA thermal budget is still open. Revisit if unattended balancing is wanted; firmware can't override a pin tied to V−. |
| 53 SDI, 54 SDO | no-connect flag | Both are NC when ISOMD = VREG (Fig. 2 footnote: "IPA, IMA, NC, NC"). |
| 55 ISOMD | VREG | isoSPI mode (unchanged from Fig. 112). |
| 56 WDT | no-connect flag | Open-drain output; Table 14 allows it to be left disconnected. The slave has no local host to read it, and the master already sees a timeout through isoSPI. |
| 43–47 GPIO5–GPIO9 | **V−** (since 2026-11-06) | Spare. The plan was for firmware to turn on their internal pull-downs (GPIOx = 0, or DCC0 = 1 for GPIO9, Table 72). **Checked 2026-11-06: the ENNOID firmware writes GPIO1–9 = 1 (pull-down off) and DCC0 = 0** (`modPowerElectronicsCellMonitorsInit()`, see `docs/master-ennoid-xlite.md`), and a watchdog timeout would restore the same defaults anyway. With no-connect flags these five inputs would float, so they are **tied straight to V−** (deviation 13). No parts; a pull-down that ever turns on just pulls an already-low pin. Keep VESC Tool "NTC sensors per module" at 4 so GPIO5 (0 V) is never read as a thermistor. GPIO5 can't join GPIO4 as an I²C pair because GPIO4 carries the onboard NTC. |

## Connectors: JST PH for the cells, JST GH for isoSPI (decided 2026-11-05, isoSPI changed 2026-11-06)

The cell and NTC connectors are JST PH (2 mm pitch, top-entry through-hole, rated 100 V / 2 A). PH
stops at 16 circuits, so the 19 cell taps split across two 10-pin headers. C9 appears on
both, so each harness half carries its own reference.

| Ref | Pins | Pinout |
|---|---|---|
| J1 CELL_TAPS_C0-C9 | 10 | pin n = C(n−1): pin 1 = C0 (V−) … pin 10 = C9 |
| J5 CELL_TAPS_C9-C18 | 10 | pin n = C(n+8): pin 1 = C9 … pin 10 = C18 (top of stack) |
| J2 NTC_3x2 | 6 | 1–2 NTC1 (GPIO1, V−), 3–4 NTC2 (GPIO2, V−), 5–6 NTC3 (GPIO3, V−); odd pin = GPIO |
| J3 ISOSPI_A_IN, J4 ISOSPI_B_OUT | 2 | **JST GH** (since 2026-11-06). Pin 1 = +, pin 2 = − (transformer line side); twisted pair, wired pin-to-pin. Pad MP = metal hold-down tabs, no circuit |
| J6, J7 (DNP) | 2 | JST PH: J6 = alternate to J3 (port A), J7 = alternate to J4 (port B), same nets (pin 1 = +). Named J6/J7 because KiCad treats a reference that does not end in a digit (J3B) as unannotated and blocks F8. Fit a PH header or solder two wires instead of using the GH |

Why these choices:

- **Voltage:** adjacent pins differ by one cell (≤ 4.2 V). The largest span across one header
  is 9 cells (37.8 V). The highest pin sits at 75.6 V to V−, under PH's 100 V rating. Keep
  J1 and J5 at least 1 mm apart on the PCB (IPC-2221 B2 asks 0.6 mm at 51–100 V).
- **Current:** balance current is about 110 mA per tap, well inside 2 A and PH's 24–32 AWG wire.
- **Shared C9:** it carries only C9's sense and balance current. If either plug is off,
  the other half still has its reference.
- **Rejected:** a single connector would mean Micro-Fit or XH 1×20 (bigger). GH is rated
  only 50 V, too little for the cell taps.
- **isoSPI is GH (2026-11-06):** JST SM02B-GHS-TB(LF)(SN), the same series as the ENNOID
  master's isoSPI port, so its cable plugs in. Data from JST eGH.pdf: 1.0 A, 50 V AC/DC, 500 V AC
  withstand for 1 min, AWG 30–26. The 50 V only has to hold the isoSPI signal between its two
  pins; the up to 151 V between the line side and the module is held by the 2 mm barrier on the
  PCB. KiCad's stock footprint matches JST's side-entry land pattern (pads 0.6 × 1.7 mm at
  1.25 mm, tabs 1.0 × 2.7 mm, 1.35 mm from the outer pin, 5.4 / 3.7 mm overall). The plug enters
  from the tab side, so that side faces the board edge.
- **The GH tabs count as line side.** They sit about 1.5 mm from the signal pads, inside the 2 mm
  barrier, so the symbol has the MP pin (no-connect) and `make_rules.py` puts the resulting
  `unconnected-(J3-…)` net in port A's line side (port B the same), like T501's pad 5.
- **J6/J7** keep the PH option: DNP, same nets, also inside the barrier and the "only isoSPI
  inside the courtyard" rules.

Risks to watch:

- PH has only a friction lock, so it can back out under vibration. Use a dab of RTV or a
  retention clip if the motor shakes it loose.
- Hot-plug: if J5 mates before J1, C9–C18 float relative to V−. The plug order (J1 first)
  and the per-cell clamps are still open below.

## Schematic nets (wired 2026-11-05)

The sheet is wired with local net labels on pin ends: labels with the same name are one net.
There are no drawn wires.

| Net | What it is |
|---|---|
| V− | Chip ground, after F120: U1 59, 60, EP 65, DTEN (52), every filter/CT/GPIO cap, R402, J2 2/4/6, D301 anode, TP1/TP2. Since 2026-11-06 it is no longer the same net as CELL0 |
| TAP0 … TAP18 | Connector side of the fuses: J1.1–J1.10 = TAP0–TAP9, J5.1–J5.10 = TAP9–TAP18 (J1.10 and J5.1 both TAP9). TAP0 also feeds F120, TAP18 also feeds F119 |
| CELL0 … CELL18 | Fused cell nodes (F1nn pin 2): R1nn and R2nn harness side. CELL0 is the C0 sense tap only (R100) |
| VBAT_F | After F119: R301 (V+), R302 (Q301 collector), D301 cathode |
| C0_F … C18_F | Filtered node at U1 pin Cn (pin 38 − 2n): R1nn output, C1nn top (n ≥ 1) |
| S1 … S18 | R2nn output to U1 pin Sn (pin 39 − 2n) |
| VP_F | After R301, at U1 V+ (pin 1) and C301 |
| VCOLL | After R302, at the Q301 collector and C302 |
| DRIVE, VREG, VREF1, VREF2, IBIAS, ICMP | Named after the U1 pin. ISOMD (55) sits on VREG |
| IPA, IMA, IPB, IMB | U1 isoSPI pins, transformer PHY+/PHY− (pins 1/3) and the 51 Ω ends |
| ISOA_CM, ISOB_CM | Midpoint of the 2 × 51 Ω termination, 10 nF to V− (C501, C601) |
| ISOA_CT, ISOB_CT | Transformer chip-side centre tap (pin 2), 10 nF to V− (C502, C602) |
| ISOA_LP / ISOA_LN, ISOB_LP / ISOB_LN | Line side: LINE+ (pin 6) to J3.1/J4.1, LINE− (pin 4) to J3.2/J4.2. Same polarity on both ports |
| GPIO1 … GPIO4 | NTC inputs (U1 39–42) |
| Zeners | D1nn: cathode (pin 1) at Cn_F, anode (pin 2) at C(n−1)_F |
| Test points | TP1, TP2 V−; TP3 VREG; TP4 VREF1; TP5 VREF2; TP6 DRIVE; TP7–TP10 IPA, IMA, IPB, IMB; TP11 VCOLL; TP12–TP14 C6_F, C12_F, C18_F |

- **PWR_FLAGs:** one each on VP_F (the net at U1 V+), VREG and V−. Nothing else needs one:
  VREF1, VREF2 and DRIVE are chip outputs, and ERC accepts the C-pin inputs on nets of
  passives.
- **No-connect flags:** U1 43–47 (GPIO5–9), 53 (SDI), 54 (SDO), 56 (WDT), and T501/T601 pin 5
  (line-side centre tap).
- **Check:** `check_slave18s.py` compares the kicad-cli netlist with the wiring table:
  366 of 366 pins (356 pin → net rows and 10 no-connects, block 6 = protection and test
  points), 0 mismatches, ERC 0/0 (2026-11-06). All 65 U1 pins are accounted for.
- **Sheet size:** 594 × 297 mm ("User"; A3 height, A2 width) since 2026-11-06, so the
  protection section sits beside the connectors.

## PCB (populated 2026-11-05, protection added 2026-11-06)

- **Import:** KiCad 10 PCB Editor, Tools → Update PCB from Schematic (F8), default options.
  The MCP `sync_schematic_to_board` was tried first and rejected: its nets lacked the `/`
  prefix that KiCad gives local labels (`V-` instead of `/V-`), and it did not copy LCSC/MPN.
  That gave 289 parity errors, so the board was reverted and F8 used instead.
- **Check** (`python _tools/kicad_sch/check_pcb_parity.py`, 2026-11-06 after the second F8):
  148 of 148 footprints, each with the footprint named in the schematic; 366 numbered pads,
  0 net mismatches against the kicad-cli netlist (PWR_FLAGs have no footprint); 29 unnumbered
  pads (U1's thermal-via/paste pads and the four NPTH holes) carry no foreign net;
  `kicad-cli pcb drc --schematic-parity`: 0 parity items.
- **Rough grouping, not placement.** Parts were moved with `_tools/kicad_sch/pcb_move.py`
  (translation only, all at 0°) into blocks inside the 120 × 70 mm placeholder: J1/J5/J2/J3
  along the top edge, balance R201–R218 (3 × 6), cell filters R1xx/C1xx, thermistors under J2,
  U1 central, supply/VREF/bias (Q301, R301/R302, C301–C305, R401/R402) below U1, isoSPI A and B
  on the right (each transformer with its R/C), and J4 bottom right. J1's last pin and J5's
  first pin are 7 mm apart (≥ 1 mm required).
- **2026-11-06 additions, also rough grouping:** the R100–R118 rows were respaced to a 5 mm
  pitch for the 1206 footprints; C101–C118 and the zeners D101–D118 sit in the same columns
  under them (D1nn under C1nn); the fuses F100–F120 and D301 below that. TP1–TP10 run along
  the bottom edge, TP11–TP14 (HV bare pads) beside Q301, H1–H4 at the bottom-left,
  bottom-right and top-right corners and the middle of the right edge (the top-left corner
  is taken by J1). 0 courtyard overlaps (pcbnew courtyard boxes), all parts inside the outline.
- **Remaining DRC items** (2026-11-06, after the protection parts; expected before placement
  and routing, not fixed):
  - 0 errors: no clearance, creepage, hole-clearance, courtyard or shorting items;
  - 256 unconnected (no routing);
  - 61 silk_overlap and 80 silk_over_copper warnings (reference text on tight groups);
  - the 16 drill_out_of_range errors on U1's 0.2 mm thermal vias are gone since the net
    classes went in: the board minimum hole is now 0.2 mm (see "U1 thermal vias").
- 3D: U1, T501 and T601 render without bodies because no 3D model is linked. This is cosmetic.

## Net classes and clearance rules (2026-11-06)

`python _tools/kicad_sch/make_rules.py` writes both: the net classes and board minimums into
`slave-18s/adbms1818-slave-18s.kicad_pro` (JSON read-modify-write, not pcbnew), and the
custom rules into `slave-18s/adbms1818-slave-18s.kicad_dru`, generated from the nets on the
board. `make_rules.py --check` passes only if both files are current **and** kicad-cli really
loads the rules. That second part matters: kicad-cli silently ignores the whole `.kicad_dru`
if one rule has a syntax error, so the check appends a canary rule to a temp copy and fails
unless it fires. Run it after any schematic change that adds or renames nets; it stops on a
net it can't place in the stack.

### Track widths

Heating doesn't set any width here. IPC-2221 (external, 10 °C rise) needs about 0.015 mm
for 114 mA and 0.003 mm for 35 mA on 1 oz copper. The widths come from U1's pin pitch (0.3 mm
pads at 0.5 mm, 0.2 mm gaps), JLC's 2 oz minimum (0.16 mm trace and space, capabilities
page, 2026-11-06), voltage drop, and robustness. 1 oz copper is 0.49 mΩ per square.

| Class | Nets | Track | Based on |
|---|---|---|---|
| HV_CELL | CELL1–18, C0_F–C18_F (and TAPn if added) | 0.25 mm | C-pin current is µA. The harness-side CELLn also carries one cell's balance current (≤ 114 mA) from the connector to R2nn. 0.25 mm runs between U1's pads at 0.5 mm pitch with 0.25 mm gaps |
| BALANCE | S1–S18 | 0.30 mm | ≤ 114 mA (sizing table below). Same as U1's pad width. 1.6 mΩ/mm on 1 oz, so 30 mm drops about 6 mV next to 3.8 V across 33 Ω |
| SUPPLY | VP_F, VCOLL, DRIVE, VREG | 0.40 mm | Q301 carries ≤ 35 mA peak (datasheet p. 71); DRIVE sources ≤ 1 mA. Wider for a short, low-inductance VREG decoupling loop. Neck down to 0.3 mm at U1 pins 1, 48 and 49. VCOLL's real job is the collector pour (placement checklist) |
| ISOSPI_PHY | IPA, IMA, IPB, IMB, ISO*_CM, ISO*_CT | 0.25 mm, pair 0.25 / 0.25 | ≤ 30 mA per pin (abs max, p. 11). Not impedance-controlled: the runs stay under 2 cm (p. 86), far shorter than the pulse edges |
| ISOSPI_LINE | ISOA_LP/LN, ISOB_LP/LN | 0.25 mm, pair 0.25 / 0.25 | Same currents, cable side of the transformers |
| Default | V−, VREF1/2, IBIAS, ICMP, GPIO1–4 | 0.25 mm | mA or less. V− (chip ≤ 35 mA plus cell 1's balance return) will mostly be a pour |

Every class keeps 0.2 mm clearance and the 0.6/0.3 mm via. Board minimums (Board Setup >
Constraints): clearance 0.16 mm (JLC 2 oz), track 0.2 mm, hole 0.2 mm (JLC's preferred
minimum, see "U1 thermal vias"), via 0.5 mm.

### Clearance: IPC-2221B Table 6-1, column B2

B2 is external conductors, uncoated, sea level to 3050 m. IPC-2221B is paywalled; the rows
were checked against two reproductions of the table on 2026-11-06 (they agree).

| Table row | B2 | Where it applies here | Set to |
|---|---|---|---|
| 0–15 V | 0.10 mm | Neighbouring cells (≤ 4.2 V), neighbouring U1 pins | 0.2 mm, net class |
| 16–30 V | 0.10 mm | Nets up to 6 cells apart (25.2 V) | 0.2 mm, net class |
| 31–50 V, 51–100 V | 0.60 mm | Nets far apart in the stack, up to 75.6 V | 0.6 mm, `.kicad_dru` |
| 151–170 V | 1.25 mm | isoSPI line side vs this module, up to 151.2 V | 2.0 mm, `.kicad_dru` |

**Why a rules file:** KiCad uses the larger of the two net classes' clearances. It can't make
the clearance depend on how far apart two nets sit in the stack, and CELL3 vs CELL4 (4.2 V)
must stay at 0.2 mm or U1's 0.5 mm-pitch pins could never be routed. So the rules file gives
each net a level (its tap number: V− = 0, top of stack = 18; VREG, VREF, GPIO and the isoSPI
chip side are level 0) and a bank = level ÷ 3, rounded down:

| Bank | 0 | 1 | 2 | 3 | 4 | 5 | 6 |
|---|---|---|---|---|---|---|---|
| Taps | 0–2 + low-voltage nets | 3–5 | 6–8 | 9–11 | 12–14 | 15–17 | 18, VP_F, VCOLL |

- Same or neighbouring bank: at most 6 levels apart, 6 × 4.2 = 25.2 V. That's the 16–30 V row,
  so the net class's 0.2 mm applies. The 6 includes an S pin, which sits up to one level
  below its tap while its switch is on.
- Two or more banks apart: up to 75.6 V, so 0.6 mm. Five rules, one per bank 0–4. Some pairs
  only 12.6–30 V apart also get 0.6 mm; that costs a little space and is on the safe side.
- Items with no net (copper text, later mounting holes) count as bank 0.

**isoSPI barrier: 2.0 mm clearance and 2.0 mm creepage** between each port's line side
(ISOA_LP/LN and T501's unconnected pad 5; the same for port B) and everything else,
including the other port's line side. The line side floats between this module and its
neighbour, so with two 18S slaves stacked (the Funwheel plan) it can sit up to 2 × 75.6 =
151.2 V from our nets: B2 row 151–170 V = 1.25 mm. 2.0 mm adds margin for motor
common-mode transients and ESD on the connector, and it costs nothing: the transformer's own
rows are 12.4 mm apart and the connector sits next to it. On a flat board without slots,
creepage equals the clearance; both constraints are in the rule so a later slot or cut-out
can't hide a short surface path.

**Mounting holes** (added 2026-11-06): `hole_clearance` 2.9 mm from the hole edge for
anything near H1–H4, which keeps copper 4.5 mm from the centre of a 3.2 mm hole, clear of an
M3 screw head or nylon washer (about 7 mm across). A copy with H4 dropped on U1 flagged it.

**Datasheet layout rules** (Rev. B p. 86, isoSPI layout guidelines), also in the rules file:
no copper pour inside T501/J3 or T601/J4 courtyards (item 2: no V− plane under the
transformer or the connector), and only that port's isoSPI tracks and vias inside them
(item 3: no traces across the isoSPI lines). Checked on a scratch copy: a V− zone under T501
is flagged, a keepout area there is not. The "nothing between transformer and connector"
part needs the placement, so it's on the checklist.

### U1 thermal vias: keep the ThermalVias footprint, board minimum hole 0.2 mm

- JLC capabilities page (2026-11-06): 2-layer minimum via hole 0.15 mm, preferred minimum
  0.2 mm. A 0.2 mm hole costs extra only when the via is under 0.45 mm across. U1's 16 vias
  are 0.2 mm holes in 0.5 mm pads (0.15 mm ring; JLC asks the via to be ≥ 0.1 mm larger than
  the hole), so they're standard price.
- The EP is U1's heat path: Table 12 gives θJA = 17 °C/W only with the EP soldered to the V−
  plane, and the 18 balance switches put their heat into the die. The vias carry it to the
  bottom-side V− copper. Dropping them to save nothing would be a bad trade.
- The vias stay open (JLC doesn't fill vias on 2-layer boards by default), so a little solder
  wicks into them. The stock footprint's 25 paste windows already allow for that. Check
  JLC's DFM report when ordering; it may flag the vias as PTH holes with a thin ring.

### DRC before and after (`kicad-cli pcb drc --severity-all`, no parts moved)

| Item | Before | After |
|---|---|---|
| drill_out_of_range (error) | 16 | 0 |
| clearance / creepage (error) | 0 | 0 |
| items_not_allowed (error) | 0 | 0 |
| silk_overlap (warning) | 22 | 22 |
| silk_over_copper (warning) | 15 | 15 |
| unconnected | 183 | 183 |
| schematic parity | 0 | 0 |

The rough grouping has no clearance problem yet: the closest pair two banks apart is 1.65 mm
(R207 CELL7 vs R213 CELL13). To prove the rules are live, a copy with the 0.6 mm raised to
3 mm flagged 266 pairs across all five stack rules.

## Placement checklist (for the Board Boxes placement pass)

Not done yet. Each item says what to check and where it comes from. Tick them in this file
when the placement is reviewed.

- [ ] **Q301 collector copper.** The SOT-223 tab (collector, VCOLL) needs a large copper
      area on both layers, stitched with vias: DS33175 gives RθJA 42 °C/W on 52 × 52 mm 2 oz
      (Tj ≈ 92 °C at 1.6 W) but 78 °C/W on 25 × 25 mm 1 oz (Tj ≈ 150 °C). Keep R302/C302
      next to the collector and C303 (VREG) next to the emitter and U1 pin 48. VCOLL sits at
      the top of the stack, so this copper is bank 6: 0.6 mm from banks 0–4.
- [ ] **isoSPI barrier.** 2.0 mm clearance and creepage from each line side (T501/T601 pins
      4–6, J3/J4, ISO*_LP/LN) to everything else; no copper pour and no foreign tracks under
      T501/J3 or T601/J4 (rules file). Datasheet p. 86: U1 within 1–2 cm of each
      transformer, the transformer within 2 cm of its connector, and the line-side pairs short
      and side by side.
- [ ] **J1/J5 spacing.** J1's last pin (TAP9) and J5's first pin (TAP9) are the same net, but
      J1 pin 1 (TAP0) and J5 pin 10 (TAP18) are 75.6 V apart: keep the two headers' far ends
      ≥ 0.6 mm apart in copper (rules file) and leave room for the plugs and the harness. Print
      "PLUG J1 FIRST" on the silk only if the zeners are left off a build.
- [ ] **Tap fuses.** F100–F120 close to J1/J5, so as little copper as possible sits before
      the fuse. Keep them away from the hot R2xx: the 0466 fuse is rated to 90 °C and derates
      with temperature.
- [ ] **Zeners.** D1nn next to U1's C pins (on the Cn_F side of R1nn), short return to the
      neighbouring Cn−1_F; they only work if they are closer to the chip than the 10 Ω.
- [ ] **TVS D301** close to F119 and R301/R302, with a short return to V−.
- [ ] **U1 EP and the V− star point.** The EP (pin 65) is soldered to a V− area with the
      ThermalVias pattern (Table 12, the EP is V−). Run V− as a star from there: the filter
      caps C1xx, VREF/VREG caps, the isoSPI caps C5xx/C6xx and F120 return to it; don't
      route the balance current through it.
- [ ] **Balance-resistor heat.** R201–R218: 0.26 W each, about 6.7 W if all 18 balance at
      once (see "Balance resistor sizing"). Spread them, give them copper, keep them away
      from U1 (die limit 80 mA above 85 °C), TH701 (it would read board heat, not cell heat),
      the fuses and the zeners.
- [ ] **Test-point reachability.** TP1–TP10 loops on the edge, on the top side, with room
      for a hook clip (≥ 5 mm between loops), labels on the silk. TP11–TP14 HV pads also
      reachable but not next to the low-voltage loops (0.6 mm rule, and fingers).
- [ ] **Mounting holes.** Choose positions with the outline; keep the 4.5 mm keep-out (rule)
      and keep the screws away from HV copper and from the isoSPI barrier.

## Open items

- [x] Build the ADBMS1818 symbol from the datasheet pin table (64-LQFP_EP). Done; netlist
      checked.
- [x] Confirm internal switch on-resistance (4 Ω typ, 10 Ω max) and the thermal limit
      (~150 °C shutdown).
- [x] Confirm VREG current (15 mA measure + 4–6.5 mA isoSPI, peaks near 35 mA).
- [x] Choose the NPN: FZT853TA. **Stock is thin (264).** Recheck before ordering.
      Collector copper must carry about 1.6 W.
- [x] Choose the isoSPI transformer: HM2113ZNL.
- [ ] Maximum balance current per S switch and the die thermal budget at 18 × ~89 mA
      (corrected 2026-11-06; 80 mA limit above 85 °C die, p. 75). If
      it's too hot, add external balance MOSFETs (datasheet Figure 99).
- [x] Collector cap C302: 100 nF 100 V (Basic C28233), per the datasheet text.
- [x] HM2113ZNL footprint: checked against Pulse BM101.C p. 2. Pin-1 dot at pad 1,
      numbered counter-clockwise, 1-2-3 on the chip side. No change needed. See "isoSPI
      transformer".
- [x] FZT853 numbering: Diodes DS33175 p. 1 pin-out (tab C; E-C-B) matches
      SOT-223-3_TabPin2 (1 = B, 2 = C/tab, 3 = E). No change needed. See "Parts".
- [x] Q301 package: **keep FZT853 (SOT-223). Decision by Racc, 2026-11-06.** He first
      read it as a 1 W part, then confirmed the 3 W rating is enough. Condition from
      DS33175: RθJA 42 °C/W on 52 × 52 mm 2 oz collector copper (Tj ≈ 92 °C at 1.6 W,
      25 °C air; ≈ 107 °C at 40 °C air), but 78 °C/W on 25 × 25 mm 1 oz (Tj ≈ 150 °C, the
      limit). So placement must give the collector tab a large copper area (both layers,
      stitched). The datasheet (Simple Linear Regulator, p. 71) sets no power figure, only
      Beta > 40 over temperature at up to 35 mA, collector ≥ 6 V above V−, 100 Ω/100 nF on
      the collector, and "attention" to heating. DPAK fallback if the copper won't fit:
      ZXTN4004K (Diodes DS35458: 150 V, hFE ≥ 60 at 85 mA, 33 °C/W on 50 × 50 mm 2 oz,
      JLC C460146/C157603, Extended), not yet fully checked.
- [x] DTEN (pin 52) to V− (discharge timer off). See "Configuration and unused pins".
- [x] WDT (pin 56) and SDI/SDO (53/54): no-connect flags.
- [x] GPIO5–GPIO9: the ENNOID firmware leaves the pull-downs off, so they are tied to V−
      (2026-11-06). The ERC pin map treats bidirectional vs power output as OK for this.
- [x] Wire the schematic. Done 2026-11-05: ERC 0 errors, 0 warnings, with PWR_FLAGs on
      VP_F, VREG and V−. See "Schematic nets".
- [x] Hot-plug protection for the plug-and-play harness. Done 2026-11-06: tap fuses,
      per-pair zener clamps and a TVS, so plug order no longer matters for the C pins. See
      "Protection and test points".
- [x] Test points and mounting holes. Done 2026-11-06 (hole positions open).
- [x] Connectors: JST PH. J1 + J5 cell taps (10 + 10, C9 shared), J2 NTCs, J3/J4 isoSPI.
- [ ] Harness: match J1/J5/J2 pin order to the Funwheel pack's tap and NTC wiring.
- [ ] ENNOID master fit (`docs/master-ennoid-xlite.md`): J3/J4 are JST GH 2P now (done
      2026-11-06); isoSPI polarity still to confirm. Firmware: the public source's LTC6813-1 driver sends only commands that
      match ADBMS1818 Table 52 (checked 2026-11-06); pick LTC6813-1 in VESC Tool. Remaining
      proof: bench test with one slave.
- [ ] Board outline (the current 120 × 70 mm rectangle is a placeholder).
- [x] Import the schematic into the PCB. Done 2026-11-05 with F8: 90 footprints, parity 0.
      See "PCB".
- [x] Net classes and HV clearance rules. Done 2026-11-06 with `make_rules.py`. See "Net
      classes and clearance rules".
- [ ] Final placement (Board Boxes), then routing.
- [x] U1 thermal vias: keep them, board minimum hole 0.2 mm (JLC preferred minimum, standard
      price at 0.5 mm diameter). See "U1 thermal vias".
- [ ] EVAL-ADBMS1818Z schematic not reviewed (not supplied). Cross-check pins and the
      transformer against it if it turns up.
