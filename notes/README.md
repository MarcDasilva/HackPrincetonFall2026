# Particle Photon 2: SDK and Device OS Notes

Notes on the Particle Photon 2 (RTL872x, Realtek) and its SDK (Device OS, Particle Workbench, Particle CLI), compiled from the Particle docs on 2026-11-13.

## Index

| File | Contents |
|---|---|
| [01-hardware-datasheet.md](01-hardware-datasheet.md) | MCU, memory, wireless, power input, mechanical, certifications, SKUs |
| [02-power-and-sleep.md](02-power-and-sleep.md) | Power consumption tables, battery, PMIC, sleep/hibernate wake rules |
| [03-gpio-and-pin-map.md](03-gpio-and-pin-map.md) | Pin-to-MCU map, boot-time pins, digital/analog/PWM/DAC, interrupts, drive strength |
| [04-serial-spi-i2c-can.md](04-serial-spi-i2c-can.md) | UART (Serial1-3), SPI, Wire (I2C), CAN, PDM microphone |
| [05-wifi-ble-network.md](05-wifi-ble-network.md) | WiFi class, BLE, Ethernet, Network, Tether, TCP/UDP, antenna and country code |
| [06-cloud-functions-variables-events.md](06-cloud-functions-variables-events.md) | Particle.function, Particle.variable, Particle.publish, Particle.subscribe, field size limits |
| [07-cloud-connection-and-system-modes.md](07-cloud-connection-and-system-modes.md) | Particle.connect/disconnect, keepAlive, process, time sync, SYSTEM_MODE, SYSTEM_THREAD |
| [08-time-timers-watchdogs-leds.md](08-time-timers-watchdogs-leds.md) | Time, chrono literals, Timer, hardware and application watchdogs, LED status, RGB, math |
| [09-data-types-and-utilities.md](09-data-types-and-utilities.md) | Variant, Buffer, Vector, Map, Ledger, NFC, Mouse, Keyboard, Servo, Stream helpers |
| [10-particle-workbench-vscode.md](10-particle-workbench-vscode.md) | VS Code extension: setup, compile and flash commands, debugging, caveats |
| [11-particle-cli.md](11-particle-cli.md) | `particle` command-line reference |
| [12-gaps-and-unverified.md](12-gaps-and-unverified.md) | What was not captured, pages that 404'd, and facts to verify before relying on them |

## Sources

- Photon 2 datasheet: https://docs.particle.io/reference/datasheets/wi-fi/photon-2-datasheet/
- Device OS firmware reference (single page, about 777 KB): https://docs.particle.io/reference/device-os/firmware/
- Particle Workbench: https://docs.particle.io/getting-started/developer-tools/workbench/
- Particle CLI reference: https://docs.particle.io/reference/developer-tools/cli/

## How to read these notes

- Content is taken from the official docs as retrieved through a summarizing fetch tool. The numbers and signatures are the docs' values, but the summarizer can drop or reword detail. Check anything safety-critical, power-critical, or limit-sensitive against the live page before relying on it.
- Version notes ("since 6.3.0") are Device OS versions. Many APIs have version-gated behavior. Pin your target with `particle flash --target` or the Workbench "Configure Workspace for Device" flow.
- Some documentation pages on the Particle site returned 404 during this pass; see [12-gaps-and-unverified.md](12-gaps-and-unverified.md).
- The Photon 2 is the RTL872x-based device (Gen 4). Anything marked "Gen 3" refers to nRF52-based devices (Argon, Boron, B-Series), and "Gen 2" to STM32-based devices (Photon, P1, Electron). Gen 4 differences are called out where they matter.

## Related

- Hardware datasheet is the authoritative source for electrical limits. Read [01](01-hardware-datasheet.md) and [03](03-gpio-and-pin-map.md) before wiring anything.
