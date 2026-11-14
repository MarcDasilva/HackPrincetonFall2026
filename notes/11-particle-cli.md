# Particle CLI Reference

Source: https://docs.particle.io/reference/developer-tools/cli/ (retrieved 2026-11-13). The page does not document `particle mesh` or most `particle cloud` subcommands, so those are omitted here.

## Notes for Photon 2 (RTL872x)

- The CLI's default target for P2 and Photon 2 is 3.2.1-p2.2, which the page does not recommend. Pass `--target 5.3.1` or later, for example `--target 5.6.0`.
- `particle setup` was removed. Use web-based setup. Only `particle serial wifi` remains for Wi-Fi credentials over serial.
- `particle serial flash` was removed in CLI 3.21.0. Use `particle flash --usb`-style DFU flashing.
- Public event stream: gone since August 2020. All events are private.
- `particle usb setup-done` does nothing on Device OS 4.0 and later.
- `particle config` is now `particle profile`. Environment and secrets live under `particle config env` and `particle config secrets`.

## Installation

- macOS and Linux: run the install script from `https://particle.io/install-cli` through `bash`. Installs `particle` to `~/bin`.
- Windows: run the self-contained installer. Installs to `%LOCALAPPDATA%\particle`. Cloud commands need internet.

## Authentication

- `particle login`: creates and saves an access token.
- `particle logout`: removes the saved token. Can optionally revoke it.

## Devices

- `particle list`: your devices, online status, variables, and functions.
- `particle call <device> <function> "<args>" [--product <id>]`: call a device function and return its result.
- `particle get <device> <variable> [--product <id>]`: read a variable.
- `particle device add <deviceId>`: claim a device. Device must be online (breathing cyan).
- `particle device rename <deviceId> "<name>"`.
- `particle device remove <deviceId>`: unclaim after confirmation. For cellular devices, this does not stop billing. Pause or release the SIM too.
- `particle identify [deviceId] [--port <port>]`: shows device ID and system firmware version over USB. Alias for `particle serial identify`.

## Flashing

### `particle flash`

Sends firmware over the air, or over USB with `--local`.

Targets:
- A project directory: `particle flash <device> .`
- A pre-compiled binary or bundle: `particle flash <device> firmware.bin` or `product.zip`
- Source files: `particle flash <device> app.ino lib.cpp lib.h`
- A known app: `particle flash <device> tinker`

Options:
- `--local`: flash over USB. Enters DFU automatically if needed. Accepts a device ID or name when several devices are connected. Example: `particle flash --local firmware.bin`.
- `--target <version>`: compile against and flash a specific Device OS. Defaults to the latest LTS.
- `--compiler local`: compile on your machine instead of the cloud (CLI 3.52.0+). Works with `--local` or an OTA target.
- `--application-only`: with `--local`, sets the compile target but does not change Device OS over USB.
- `--serial`: flash in listening mode (dark blue). DFU is more reliable and is the normal choice.
- `--factory`: update the factory reset firmware slot, if supported. Does not restore original Device OS.

Examples:
```
particle flash 0123456789abcdef78901234 . --target 5.6.0
particle flash --local tinker --target 5.5.0
particle flash --local project/path --target x.y.z --application-only
```

Notes:
- Flashing `tinker` leaves Device OS unchanged unless `--target` is given.
- `particle update` also updates the NCP on Tracker devices. `--local` does not, though NCP can be updated OTA.
- Projects with `assetOtaDir` in `project.properties` flash as a bundle with Asset OTA assets.

### `particle cloud flash`

Compiles in the cloud and flashes a product device:
```
particle cloud flash 0123456789abcdef01234567 --product 12345
```
If the device is not marked as a development device, product firmware may overwrite it.

## Compiling

### `particle compile <platform> <source>`

Compiles in the cloud and saves the binary locally.

Platforms: `p2` (Photon 2), `boron`, `argon`, `bsom` (B-Series SoM 4xx), `b5som` (B-Series SoM 5xx), `tracker`, `photon`, `p1`, `electron` (E-Series).

Options:
- `--saveTo <file>`: output filename. Overwrites.
- `--target <version>`: Device OS version to compile against.
- `--compiler local`: compile on your machine (CLI 3.52.0+). Does not need Workbench. Supports community libraries and asset bundles.

Examples:
```
particle compile boron myapp.ino
particle compile p2 . --saveTo firmware.bin
particle compile boron my_project --compiler local --target 6.4.1
```

Limits: cloud compile times out at 120 seconds. Source capped at 50 MB.

Notes:
- `.ino` and `.cpp` are processed differently. The cloud adds missing prototypes and `#include "Particle.h"` to `.ino` files if needed.
- Shared Arduino libraries can use `#if defined(ARDUINO)` / `#elif defined(SPARK)` include guards.
- Asset bundles are `.zip` files that contain the binary and assets.
- Older devices need older targets (Xenon: 1.5.x or earlier; Spark Core: 1.4.4 or earlier).

## Bundles

### `particle bundle <file.bin>`

Creates an Asset OTA `.zip` from a compiled binary and assets.

- `--assets <path>`: asset directory or `project.properties`. Defaults to `assetOtaDir`.
- `--env <file.json>`: includes environment variables.
- `--saveTo <file.zip>`.

Set assets with `assetOtaDir=assets` in `project.properties`, relative to the project root.

## Device protection (Device OS 6.x enterprise)

Blocks local flashing over USB or SWD/JTAG and blocks USB serial. Requires login and access to the device's product. Protection cannot be removed through the CLI. Commands accept `--device <id>` if several devices are connected.

- `particle device-protection status`
- `particle device-protection disable`: temporarily disables for USB serial and other features.
- `particle device-protection enable`: most commands re-enable it automatically. Exceptions: `particle usb reset` and `particle serial monitor`.

## Projects

- `particle project create [--ai]`: prompts for a name and location (default home directory). `--ai` adds `AGENTS.md` for AI coding agents.
- `particle project ai`: adds `AGENTS.md` to an existing project.
- Metadata lives in `project.properties`.
- From the project directory: `particle compile photon`, `particle flash my_device`.

## Libraries

- `particle library list`: popular libraries.
- `particle library search <name>`: case-insensitive.
- `particle library add <name>[@version]`: adds to the project. Re-running upgrades to the latest.
- `particle library view <name>`: downloads and shows the local path.
- `particle library copy <name>`: copies into `lib/` for local edits. Remove it from `project.properties` first if it was added with `library add`.
- `particle library create`: creates a folder structure. Run in an empty directory.
- `particle library upload`: uploads a private version from the current directory. Edit `library.properties` for a modified library's name.
- `particle library publish <name>`: publish a private version. Must be done before others can use it.

## Webhooks (user webhooks only)

- `particle webhook create <eventName> <url> [deviceId]`.
- `particle webhook create <file.json>`: from a JSON definition.
- `particle webhook list`.
- `particle webhook delete <hookId>`.
- `particle webhook delete all`: after confirmation.

## Monitoring and events

- `particle monitor <deviceId|all> <variable> <intervalMs> [--time]`: polls a variable. Minimum 500 ms. Ctrl+C to exit. Redirect output to a file for CSV logging.
- `particle subscribe [eventName] [deviceId|--device <id>] [--product <id>]`: streams events. Names are prefix-matched.
- `particle publish <eventName> [data] [--product <id>]`: publishes as if from a device.

## Wi-Fi

Works in listening mode and normal mode, not DFU. Gen 3 and later (Argon, P2, Photon 2, M-SoM) scan on the device.

- `particle wifi add [--file creds.json]`: stores credentials without connecting. Supports hidden SSIDs. Requires Device OS 5.8.2+ or 6.2.0+.
- `particle wifi join [--ssid <ssid>] [--file creds.json]`: stores (if given) and joins. `--ssid` joins a stored network.
- `particle wifi list`: visible networks.
- `particle wifi clear`: removes all stored credentials. Does not disconnect.
- `particle wifi remove --ssid <ssid>`: removes one credential. Does not disconnect.
- `particle wifi status`: current network.

Credentials file:
```json
{ "network": "my_ssid", "security": "WPA2_PSK", "password": "my_password", "hidden": false }
```
Security types: `NONE`, `WEP`, `WPA`, `WPA2_PSK`, `WPA3_PSK`.

## Serial

- `particle serial wifi [--file creds.json]`: sets Wi-Fi over serial. Required for WPA Enterprise (Photon and P1 only). Devices on Device OS 6.2+ should use `particle wifi`.
  - Security values: `NONE`, `WEP`, `WPA2_AES`, `WPA_TKIP`, `WPA2_AES+TKIP`. Enterprise uses `WPA_802.1x` or `WPA2_802.1x` with `eap`, `username`, `outer_identity`, `client_certificate`, `private_key`, `root_ca`.
  - Gen 2 devices scan from the computer's Wi-Fi, which may see different networks than the device.
- `particle serial identify`: same as `particle identify`.
- `particle serial list`: USB serial devices.
- `particle serial monitor [--port <port>]`: read-only serial monitor.
- `particle serial inspect`: reports firmware modules, versions, integrity checks. Any `FAIL` usually means a missing dependency such as a bootloader needing an upgrade. Often fixable OTA.
- `particle serial mac`: prints MAC address.

## USB

Device OS 0.9.0+ (Gen 3 including Argon and Boron) and 1.0.0+ (Gen 2). Not Gen 1. On Windows 10 you may need current drivers.

- `particle usb list [--exclude-dfu] [--ids-only]`.
- `particle usb start-listening [devices...] [--all]` (alias `listen`): needs normal or safe mode.
- `particle usb stop-listening [devices...] [--all]`: needs listening mode.
- `particle usb safe-mode [devices...] [--all]`: needs normal mode.
- `particle usb dfu [devices...] [--all]`: needs normal or safe mode.
- `particle usb reset [devices...] [--all]`: works from any mode.
- `particle usb send-request '<json>'`: custom USB control request. Example `'{"op":"status"}'`.
- `particle usb env [device|--all]`: reads environment variables. Cannot set over USB. Use `particle config env`.
- `particle usb setup-done [devices...] [--reset]`: Gen 3 on Device OS 3.x or earlier. Needs normal or safe mode.
- `particle usb configure`: installs udev rules on Linux.

## Updating Device OS

### `particle update [--target <version>]`

Updates Device OS. Defaults to latest LTS, or latest non-RC developer preview if no LTS. Follow with `particle flash --local tinker` to restore known-good software.

Downgrade cautions:
- Avoid downgrading except to move from developer preview back to the adjacent LTS.
- Downgrade user firmware first, or flash Tinker. User firmware targeting a newer Device OS may upgrade the device back after reconnecting.
- Boron LTE (BRN402) and B-Series SoM (B402): going from 2.0.0+ to 1.5.1 or earlier requires installing 1.5.2 first. Let the device connect to cellular, then downgrade. The newer firmware uses a higher modem baud rate older firmware cannot match.

## Config, environment, and secrets

Environment variables: non-secret name-value pairs for runtime settings. Scope: org, sandbox, product, or device.
- `particle config env list [--org <org> | --sandbox | --product <id> | --device <id>]`
- `particle config env set <name> <value>` or `<name>=<value>`, with a scope flag.
- `particle config env delete <name>`, with a scope flag.
- Changes are staged in the cloud. Review and roll out in the Particle console.

Secrets: organization-scoped values that integrations can reference.
- `particle config secrets list [--org <org> | --sandbox] [--json]`
- `particle config secrets get <name>`, with a scope flag.
- `particle config secrets set <name> <value>` or `<name>=<value>`, with a scope flag.
- `particle config secrets delete <name>`, with a scope flag.

## Keys (requires OpenSSL)

- `particle keys doctor [deviceId]`: regenerates device keys and sends the public key to the cloud. Fixes out-of-sync keys.
- `particle keys new [name]`: new key pair. Default name `<deviceId>.der`.
- `particle keys load [file.der]`: writes a private key to the device's external flash. Backs up the existing key first. Send the matching public key with `particle keys send`.
- `particle keys save [file.der]`: backs up the device's private key to your computer.
- `particle keys send [deviceId] [file]`: uploads a public key to the cloud.
- `particle keys server [file.der] [--host <addr>] [--port <port>]`: sets the server public key. Device stays in DFU afterward. No file restores the default. `--host` and `--port` are for local cloud setups.
- `particle keys address`: shows server address, port, and protocol on the device.

## Profiles

- `particle profile`: current profile, API URL, access token.
- `particle profile <name>`: switch. `particle profile particle` returns to default.
- `particle profile <name> apiUrl <url>`: create or update a setting (for example a local server).
- `particle profile useSudoForDfu true`: sets an option.

## Other

- `particle nyan [deviceId|all] [on|off]`: rainbow LED sequence. Useful to identify a device.
- `particle binary inspect <file>`: CRC, target platform, module dependencies of a binary or bundle.
- `particle token create [--expires-in <seconds>] [--never-expires]`: default lifetime 90 days. Use non-expiring tokens only for hosted apps.
- `particle token revoke <token> [--force]`: `--force` is required to revoke the CLI's own token.

## Product (beta)

- `particle product device add <productId> <deviceId>` or `--file <ids.txt>` (one device ID per line).
- `particle product device list <productId>`.
