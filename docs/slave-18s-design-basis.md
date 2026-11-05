# ADBMS1818 18S slave: design basis

Status: **parts placed, unwired, 2026-11-05.** Every part is on the root sheet with Value,
Footprint, LCSC and MPN filled in, grouped by function. Wiring is done by hand in KiCad.
The JLC BOM is `slave-18s/bom.csv`.

## Scope

- One ADBMS1818 monitoring up to 18 series Li-ion cells (4.2 V max each, 75.6 V stack).
- isoSPI daisy chain: port A in, port B out (ISOMD tied to VREG).
- Passive balancing through the internal S-pin switches.
- Thermistor inputs on GPIOs.
- No power switching and no charge control. Those live in the master.

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
| DRIVE regulator | NPN, 100 Ω from top of stack to collector, 10 nF (100 V) at the collector, 1 µF at VREG (emitter) | Datasheet text recommends a 100 Ω / **100 nF** collector RC. Figure 112 shows 10 nF |
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
   working while the motor runs. The datasheet (Figure 104) describes the same split
   termination as a noise option.
2. **Regulator NPN in a big package.** Dissipation ≈ (V_stack − I·100 Ω − 5 V) × I_reg. At
   75.6 V and 20–23 mA (measure + isoSPI) that's about 1.4–1.6 W, with peaks near 35 mA.
   FZT853 (SOT-223, 3 W on 52 × 52 mm of 2 oz copper) needs generous collector copper.
3. **Thermistors:** 100 kΩ pull-up to VREF2, 100 kΩ NTC, 100 nF on the GPIO (Racc's
   arrangement). Three cell NTC inputs on GPIO1–3 and one onboard 0603 NTC on GPIO4.
4. **Balance resistor 33 Ω in 2512 (1 W).** See sizing. Two 68 Ω 1206s were the
   alternative, but C17976 (68 Ω 1206) is an Extended part too, and each 1206 would run at
   about 82 % of its 0.25 W rating on a board that heats up while balancing.
5. **isoSPI transformer HM2113ZNL instead of HX1188FNL.** See the transformer section.

## Balance resistor sizing

Uses the datasheet switch resistance (4 Ω typ, 10 Ω max).

| R_S | I at 4.2 V (4 Ω switch) | I at 4.2 V (10 Ω switch) | P in R_S at 4.2 V |
|---|---|---|---|
| 120 Ω (Racc's board) | ~34 mA | ~32 mA | 0.14 W |
| 47 Ω | ~82 mA | ~74 mA | 0.32 W |
| **33 Ω (Fig. 112)** | **~114 mA** | **~98 mA** | **0.43 W** |

- 0.43 W in a 1 W 2512 is about 43 % loading.
- All 18 balancing at once is about 8 W on the board. Firmware should balance odd and even
  cells alternately, or the layout needs copper for heat spreading.

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

## Parts and JLC numbers

All picks were checked on jlcpcb.com/partdetail on 2026-11-05 (Basic/Extended flag and stock).

| Ref | Part | Footprint | LCSC | Type | Stock |
|---|---|---|---|---|---|
| U1 | ADBMS1818ASWAZ-RL | LQFP-64-1EP 10×10, EP5×5 | C5372802 | Extended | 12,496 |
| R100–R118 | 10 Ω 1 % | 0603 | C22859 | Basic | 5.8 M |
| C101–C118, C301 | 100 nF 100 V X7R | 0805 | C28233 | Basic | 3.25 M |
| R201–R218 | 33 Ω 1 % 1 W | 2512 | C53728 | Extended | 49,062 |
| R301 | 100 Ω 1 % (V+) | 0603 | C22775 | Basic | 8.6 M |
| R302 | 100 Ω 1 % 150 V (collector) | 0805 | C17408 | Basic | 7.4 M |
| C302 | 10 nF 100 V X7R (collector) | 0603 | C282516 | Extended | 463 k |
| Q301 | FZT853TA, NPN 100 V 6 A 3 W | SOT-223 | C435890 | Extended | 264 |
| C303–C305 | 1 µF 50 V X5R (VREG, VREF1, VREF2) | 0603 | C15849 | Basic | 11.9 M |
| R401, R402 | 1 kΩ 1 % | 0603 | C21190 | Basic | 28 M |
| T501, T601 | Pulse HM2113ZNLT | Pulse_HM2113ZNL | C5730533 | Extended | 6,533 |
| R501, R502, R601, R602 | 51 Ω 1 % | 0603 | C23197 | Basic | 2.0 M |
| C501, C502, C601, C602 | 10 nF 50 V X7R | 0603 | C57112 | Basic | 5.3 M |
| R701–R704 | 100 kΩ 1 % (NTC pull-ups) | 0603 | C25803 | Basic | 16.6 M |
| C701–C704 | 100 nF 50 V X7R (GPIO) | 0603 | C14663 | Basic | 36.6 M |
| TH701 | Murata NCP18WF104F12RB, 100 k 1 % B 4250 K | 0603 | C71280 | Extended | 115 k |
| J1–J4 | Connectors | TBD | TBD | | |

There are 7 Extended lines. C302 could become Basic C28233 (100 nF 100 V) if the collector
cap follows the datasheet text instead of Figure 112.

Why these values are safe at the voltages involved:

- The 0603 thick-film resistors are rated 75 V. Each one only sees cell-level or IR-drop
  voltages.
- The termination and CT caps (C5xx/C6xx) and the GPIO caps sit near V− (< 6 V), so
  50 V parts are fine there.

Rejected NPN options: PBSS8110Z (0 stock), NSS1C201MZ4 (93 stock), FZT493TA (0 stock),
PZTA42 (300 V, but hFE min only 25–40; the datasheet asks for > 40 over temperature).

## Connector candidates (harness not decided)

| Function | Pins | Candidates |
|---|---|---|
| Cell taps C0–C18 | 19 (+1 spare) | Molex Micro-Fit 3.0 2×10 (3 mm, 5 A, 600 V); JST XH 1×20 (2.5 mm, 250 V, long); Würth WR-MPC3 2×10; JST GH 1.25 mm (only 50 V rating, too low for the end-to-end stack) |
| Cell NTCs | 6 (3 × 2) | JST PH 1×6 (2 mm); JST GH 1×6; 3 × JST PH 2-pin |
| isoSPI A in / B out | 2 each | Molex Micro-Fit 3.0 1×2 or Micro-Lock Plus; JST GH 1×2 (signals sit near V− of the module); twisted pair |

For plug-and-play, put C0 and C18 at opposite ends of the cell-tap connector, and choose a
pin order whose partial mating can't put the full stack across two adjacent pins.

## Open items

- [x] Build the ADBMS1818 symbol from the datasheet pin table (64-LQFP_EP). Done; netlist
      checked.
- [x] Confirm internal switch on-resistance (4 Ω typ, 10 Ω max) and the thermal limit
      (~150 °C shutdown).
- [x] Confirm VREG current (15 mA measure + 4–6.5 mA isoSPI, peaks near 35 mA).
- [x] Choose the NPN: FZT853TA. **Stock is thin (264).** Recheck before ordering.
      Collector copper must carry about 1.6 W.
- [x] Choose the isoSPI transformer: HM2113ZNL.
- [ ] Maximum balance current per S switch and the die thermal budget at 18 × ~110 mA. If
      it's too hot, add external balance MOSFETs (datasheet Figure 99).
- [ ] Collector cap C302: keep Figure 112's 10 nF (Extended) or use the text's 100 nF
      (Basic C28233)?
- [ ] HM2113ZNL footprint: pads are numbered counter-clockwise from the pin-1 dot. Confirm
      against a real part or the Pulse 3D model before ordering.
- [ ] FZT853 numbering: the Diodes datasheet shows B–C–E leads (tab C) without numbers.
      KiCad SOT-223-3_TabPin2 assumes pin 1 = B. That's standard, but check the outline page.
- [ ] DTEN (pin 52): not shown in Figure 112. Tie to VREG to enable the discharge timer,
      or to V−.
- [ ] WDT (pin 56): leave open or add 1 MΩ to VREG. SDI/SDO (53/54) are NC in isoSPI mode:
      add no-connect flags.
- [ ] GPIO5–GPIO9 unused: decide (spare NTC, LED, I²C).
- [ ] KiCad ERC reports unconnected pins as **errors**, not warnings (299 on the unwired
      sheet: pin_not_connected, pin_not_driven, power_pin_not_driven). They disappear as
      the circuit is wired. V+, VREG and V− will need PWR_FLAGs.
- [ ] Hot-plug protection for the plug-and-play harness (connector pin order, per-cell
      clamps).
- [ ] Connector and harness pinout matched to the Funwheel pack (candidates above).
- [ ] Board outline (the current 120 × 70 mm rectangle is a placeholder).
- [ ] EVAL-ADBMS1818Z schematic not reviewed (not supplied). Cross-check pins and the
      transformer against it if it turns up.
