# Master: ENNOID Master-XLITE-ISC (bought, not designed here)

Decision 2026-11-06: the slave in `slave-18s/` works under a bought ENNOID master,
the **Master-XLITE-ISC** (supplied by a friend). This repo doesn't design a master. The
standard Master-XLITE would work the same way: it differs in connectors (JST PH 2.0 mm
instead of GH 1.25 mm), uses two-sided assembly, and adds a push-button with LED, I²C
display bus and pre-discharge/discharge outputs.

Sources:
- Pinout sheet `Master-XLITE-ISC-PINOUT.pdf` (3 pages), kept locally as
  `_reference/datasheets/ENNOID_Master-XLITE-ISC_pinout.pdf`. It is ENNOID's document, so
  it is gitignored like the other vendor datasheets and is not published.
- Product page: https://www.ennoid.me/bms/master-xlite (read 2026-11-06).

## How the system fits together

```
 charger --XT30--> [ Master-XLITE-ISC ] --XT30--> pack (BAT+ / BAT-)
                    |  charge FETs, CAN (GH 4P), Bluetooth, VESC Tool
                    |
                    +-- isoSPI (JST GH 2P, 2 wires, <= 2 m per hop)
                          |
                    [ this 18S slave ]  J3 = isoSPI A (IN, from master)
                          |             J4 = isoSPI B (OUT, to next slave)
                          +-- next slave ... (up to 20 slaves)
                          |
                    cell taps J1/J5 + NTCs J2 --> pack harness
```

- **Master** (charge only): charger and battery XT30s, the charge MOSFETs, pack and charger
  voltage, charge current, SoC/SoH, isolated CAN (default ID 10), Bluetooth, buzzer, status
  LED, auto wake/shutdown. Firmware is ENNOID's VESC-Tool-compatible BMS firmware (6.06 adds
  "Support for parallel packs and 18s slaves").
- **Slave** (this repo): measures cells, balances, reads thermistors, and passes isoSPI on.
  No pack current, no XT30s, no FETs. That's why the XT30 step was dropped on 2026-11-06.

## What the pinout sheet says that matters for the slave

| Item | ENNOID | This slave | Status |
|---|---|---|---|
| isoSPI connector | JST GH 2P on master and ENNOID 18S slaves | J3/J4 JST PH 2P | **Open:** swap J3/J4 to GH 2P, or use a GH-PH cable |
| isoSPI pin polarity | labelled on master silk (not readable in the PDF) | pin 1 = +, pin 2 = − | **Open:** confirm with the master's cable / footprint |
| Thermistor default | NTC 100 kΩ, B 4250 | 100 kΩ pull-ups + TH701 NCP18WF104F12RB (100 k, B 4250) | Matches |
| C0 | "C0 correspond to the slave negative voltage reference" | TAP0 / V− | Matches |
| Cells per slave | 3 minimum; unused top inputs bridged to the top cell (14S example: C14–C18 shorted) | 18 | OK |
| Balance connector | JST GH 13P + 6P (GH is rated 50 V) | J1/J5 JST PH 10P + 10P (PH 100 V, ≤ 37.8 V per header) | Keep PH on purpose |
| Slaves per chain | up to 20, ≤ 2 m between slaves | — | OK |

VESC Tool settings from the sheet's 32S example (14S + 18S slaves): "First monitoring IC cell
num", "Last monitoring IC cell num", "Cell num", "monitoring IC num". For one 18S slave this
should be 18 / 18 / 18 / 1 (not yet tried).

## Open questions

- **Monitoring IC support.** ENNOID documents LTC6811/6812/6813 slaves. This slave uses the
  ADBMS1818, which ADI offers as the newer part next to the LTC6813-1. Command and register
  compatibility is not yet checked against both datasheets or the ENNOID firmware source.
- Which GPIOs the firmware reads for temperature (we use GPIO1–4).
- Whether the last slave's port B needs anything when nothing is plugged into J4.
