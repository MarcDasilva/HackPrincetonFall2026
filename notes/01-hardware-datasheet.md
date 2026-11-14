# Photon 2 Hardware Datasheet

Source: https://docs.particle.io/reference/datasheets/wi-fi/photon-2-datasheet/ (retrieved 2026-11-13 via summary; verify exact figures on the live page).

## MCU and processing

- MCU: Realtek RTL8721DM, ARM Cortex-M33 CPU at 200 MHz.
- Minimum Device OS: 5.0.0. The datasheet recommends the latest 5.x release.

## Memory and storage

- User application maximum size: 2048 KB (2 MB).
- User-available RAM: 3072 KB (3 MB), drawn from 512 KB SRAM and 4 MB PSRAM.
- Flash file system: 2 MB.
- Retained memory: 3068 bytes (Device OS 5.3.1+).
- Flash layout (do not overwrite the first partitions):
  - `0x00000000` prebootloader-mbr (factory configured, do not overwrite)
  - `0x00004000` bootloader
  - `0x00014000` prebootloader-part1
  - `0x00060000` system-part1
- Do not chip-erase the RTL872x. Doing so removes the factory partitions.

## Wireless

- Wi-Fi: 802.11 a/b/g/n, 2.4 GHz and 5 GHz.
- Bluetooth: BLE 5, sharing the Wi-Fi antenna. BLE Central mode requires Device OS 5.1.0+.
- Antenna options:
  - Integrated PCB trace antenna (default).
  - U.FL connector for an external antenna, with an integrated RF switch. Antenna is selected in software (see [05-wifi-ble-network.md](05-wifi-ble-network.md)).
- Approved external antennas: PARANTWM1EA (single unit), PARANTWM1TY (x50).
- Do not use the Argon antenna (ANT-FLXV2). The docs say it does not work well on 5 GHz.
- PCB antenna figures:
  - 2.4 GHz gain: 2.41 dBi.
  - 5 GHz bands gain: 1.21 to 1.74 dBi.
  - 2412-2462 MHz: 0.376704 W transmit power.
  - 5.5 GHz band: 0.097949 W and 0.091833 W.

## Power input and output

- USB: micro-B connector, needs at least 500 mA.
- VUSB pin: about 4.5 to 5 VDC when USB is connected, 0 when not. Rated 500 mA nominal, internal 1000 mA fuse. There is no blocking diode to USB, so do not power the board from VUSB and USB at once.
- LiPo: single-cell 3.7 V with JST-PH connector and on-board charger. Check polarity before connecting.
- Li+ pin: input range 3.6 to 4.2 VDC.
- 3V3 output: 3.3 V regulator, 500 mA max. The docs say it cannot power the Photon 2 (it is an output, not a supply input).
- EN pin: has a 100K pull-up. Never drive it from a 3.3 V GPIO. Use an open-drain driver or MOSFET to pull it low.
- Charge LED: on while charging, off when charge is complete.
- Battery voltage: `analogRead(A6) / 819.2` (reads 0 to 5 VDC). No fuel gauge on this board.
- The CHG pin cannot be read reliably on current hardware.

## Mechanical

- Dimensions: not given in this datasheet. Form factor is similar to the Argon (Adafruit Feather).
- Headers: one 16-pin and one 12-pin single-row, 0.1 inch pitch.
- Matching female header height: about 0.335 in (8.5 mm).
- 3D models (STEP, IGES, F3Z) are in the Particle hardware-libraries GitHub repository.
- Assembly:
  - Use a socket for base-board attachment. The module is not designed for surface-mount or paste-in-hole reflow.
  - Use no-clean flux if soldering directly. Do not use water-soluble flux.
  - Do not apply conformal coating. Use an enclosure for waterproofing.

## Environmental

- Operating temperature: -20 °C to +70 °C.
- Humidity: up to 95% RH, non-condensing.
- MSL and ESD notes in the datasheet refer to the P1 module (MSL level 3).

## Certifications

- FCC ID: 2AEMI-P2 (FCC Part 15, Class B).
- ISED (Canada): 20127-P2.
- CE (EU) and UKCA (UK).
- RoHS.
- Japan: R210-274205.
- Outdoor 5 GHz limits: FCC allows EIRP 125 mW (21 dBm) at elevations above 30° in U-NII-1. Canada restricts 5150-5250 MHz to indoor use.
- Keep at least 20 cm between the radiator and the body.

## Ordering SKUs

| SKU | Description | Status |
|---|---|---|
| PHN2KIT | Photon 2 kit (x1) | GA |
| PHN2MEA | Photon 2 (x1) | GA |
| PHN2MTY | Photon 2 tray (x50) | GA |
| PHN2EDGEKIT | Edge ML Kit | Deprecated |

## Known errata

- None listed.
