# Gaps, Failed Fetches, and Facts to Verify

These notes were built in one pass. This file records what is missing or uncertain, so the next pass knows where to look.

## Pages that returned 404 or were not captured

- `https://docs.particle.io/reference/device-os/api/cloud-functions/particle-variable/` was linked from search results as "Cloud functions," but the variable section content was captured from the single-page firmware reference instead.
- `https://docs.particle.io/reference/device-os/api/events/publish/` returned 404.
- `https://docs.particle.io/reference/device-os/api/events/particle-publish/` returned 404.
- `https://docs.particle.io/reference/device-os/api/cloud-variables/particle-variable/` returned 404.
- `https://docs.particle.io/reference/device-os/api/` redirects to `/reference/device-os/api/introduction/getting-started`, which did not contain API index content when fetched.
- `https://docs.particle.io/getting-started/start/photon-2/` returned 404. The Photon 2 getting-started guide (LED status meanings, setup, button behaviors, first flash) is NOT in these notes. This is the biggest gap for a new user.
- `https://docs.particle.io/reference/device-os/api/publish/particle-publish-publish/` and related paths appeared in search results but were not fetched.
- The typed-publish page (`https://docs.particle.io/reference/device-os/typed-publish/`) was not fetched. It holds Device OS 6.3.0+ rate limits for publish.
- `https://docs.particle.io/quickstart/workbench/`, the Workbench install page, was referenced but not fetched.
- `https://docs.particle.io/getting-started/device-os/introduction-to-device-os/` appeared in search results and was not fetched.

## Sections missing from the single-page firmware reference

The firmware reference is about 777 KB. The notes cover the first ~700 KB in summary form. Sections the summaries did not give full detail on, or skipped:

- System class: `System.reset()`, `System.sleep()` (all modes and arguments), `System.enableUpdates()` and `disableUpdates()`, `System.factoryReset()`, reset reason, `System.version()`, `System.freeMemory()`, `System.threadingEnabled()`, `System.enableFeature()` and `disableFeature()`, `System.backupRamSync()` beyond the mention in the power notes.
- System modes section in detail (AUTOMATIC, SEMI_AUTOMATIC, MANUAL section text).
- EEPROM API.
- OTA update behavior and `System.enableUpdates()` details.
- `Log` API: `Log.info`, `Log.trace`, `Log.error`, log categories, `SerialLogHandler`, `Log.enableHandler` pattern.
- Cellular: beyond the summary in [05-wifi-ble-network.md](05-wifi-ble-network.md), the Cellular class has deeper sections (command(), CellularGlobalIdentity, FuelGauge details) that were only partially summarized.
- Ethernet: the summaries are good, but the section on DHCP vs. static setup examples is not captured.
- Mouse `begin()` details beyond the reconnect note.
- Math (`math.h`) section, which was truncated.
- Buffer's non-const `data()` details and beyond.
- RGB mirror options beyond `mirrorDisable()`.
- PDM microphone API (the `Microphone_PDM` library, beyond the pin mapping).
- Serial `halfduplex`, `acquireSerial*Buffer` examples, and LIN mode.
- Any content after the `LEDStatus` and `Math` sections (the firmware page continues beyond ~777 KB in the summarizer's view; re-fetch with offsets above 700000 if needed, although the last fetch ended in the Math section).

## Facts the summaries flagged as uncertain

- The Cloud function "return value" range: the docs say it is a 32-bit `int`. Confirm the failure convention and any reserved values.
- Cloud call timeout duration for `Particle.function`: the docs do not say. Measure it on your device if your app depends on it.
- Cloud call rate limits for functions and variables: not specified in the captured content.
- Variable data limit cell marked "622" in the summary's table for "before 0.8.0": the source appears to include a footnote marker. Confirm.
- Publish rate limit for Device OS 6.3.0+: deferred to the typed-publish page, not captured.
- `Particle.publish` blocking time: "about 20 seconds normally, up to 10 minutes in unusual conditions." Verify before relying on it in a loop.
- The DAC section for Photon 2: the datasheet does not list DAC channels, and the firmware reference's DAC section describes Gen 2 only. Treat Photon 2 DAC as unknown.
- CAN on Photon 2: the CAN API is documented as Gen 2 only. The datasheet does not list CAN for Photon 2. Treat as unsupported unless confirmed.
- Photon 2 `dimensions` (in mm or inches): not in the datasheet summary. Get from the hardware-libraries GitHub 3D model or the datasheet's drawing.
- Photon 2 `Keyboard` and `Mouse` support: the summary says P2 and Photon 2 support it from 5.4.0. Confirm for your exact OS version.
- BLE connection limit on Photon 2: "4 open links" for Gen 4 (P2, Photon 2, M-SoM). Confirm.
- Wi-Fi credential storage limit: 10 on P2, Photon 2, Argon. Confirm.
- Ethernet on Photon 2: the Ethernet section lists pin remaps for external modules. The Photon 2 board itself does not have Ethernet. Confirm for your exact hardware.

## Things intentionally not done

- No code was compiled or run against hardware. These notes are documentation only.
- No device was flashed and no CLI command was executed.
- Pages were not checked for changes after 2026-11-13.

## Suggested next pass

1. Find the working URL for the Photon 2 getting-started guide and capture LED meanings and first-flash steps.
2. Fetch the single-page firmware reference using `offset` values 0, 100000, ... 700000 again for the System class and EEPROM, OTA, Log sections. The current pass may have skipped them because of how the summary tool windows the text.
3. Fetch the typed-publish page for 6.3.0+ publish rate limits.
4. Fetch the Device OS introduction page for version support notes.
5. Fetch the Workbench quickstart page for install steps.
