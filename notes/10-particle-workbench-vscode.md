# Particle Workbench (VS Code Extension)

Source: https://docs.particle.io/getting-started/developer-tools/workbench/ (retrieved 2026-11-13). The install steps are on a separate quickstart page (`/quickstart/workbench/`), which was not captured here.

## Prerequisites and setup

- Workbench is a Visual Studio Code extension.
- Login: cloud compile and flash need a Particle account. Use **Particle: Login** (2FA codes if enabled). Use **Particle: Logout** on shared computers.
- Dependency manager: Workbench downloads the Device OS, build system, and compiler to a private user-space location.
  - **Particle: Install Local Compiler** adds a Device OS version.
  - **Particle: Uninstall Local Compiler** removes one.
  - **Particle: Reset Environment** reinstalls compilers to fix a corrupted install.
- Pre-release builds: Settings > Extensions > Particle, then enable pre-release Device OS builds. Afterward, **Particle: Configure Workspace for Device** lists more versions.
- IntelliSense depends on Microsoft's C/C++ extension, which Workbench configures automatically.

## Device OS, platform, and device selection

- Run **Particle: Configure Workspace for Device**. Choose, in order:
  1. Device OS version
  2. Device type
  3. Device name or ID (can be blank for USB flashing or build-only testing)
- Selections are saved in the project's `.vscode/settings.json`.

## Project creation and structure

- **Particle: Create New Project** creates a preconfigured folder.
- **Particle: Import Project** adds VS Code files to an existing project that has a `project.properties` file.

Layout:
- `.vscode/`: project settings (Device OS version, platform, device).
- `src/`: source files. A `.ino` file is converted to `.cpp` at build time.
- `lib/`: local library source.
- `target/`: local build output, organized by Device OS version and platform.
- `*.bin` at the top level: result of a cloud compile.
- `project.properties`: list of libraries and dependencies.
- `README.md`: project documentation.
- `particle.include` and `particle.ignore`: control which files upload for cloud compiles.

## Compile and flash commands

Cloud (web build):
- **Particle: Cloud Compile**: compiles in the cloud and downloads the binary to the project root.
- **Particle: Cloud Flash**: compiles in the cloud and flashes over the air.
- Limits: 120 s maximum compile time, 50 MB maximum source size.

Local (on your machine; works offline once installed):
- **Particle: Compile application (local)**: user firmware only. Output to `target/<version>/<platform>/`.
- **Particle: Compile application & DeviceOS (local)**: builds Device OS and user firmware.
- **Particle: Compile application for debug (local)**: monolithic debug binary.
- **Particle: Flash application (local)**: builds and flashes user firmware over USB. Usual choice. Flashes Device OS only if an upgrade is needed.
- **Particle: Flash application & DeviceOS (local)**: builds and flashes both. Always flashes the targeted Device OS.
- **Particle: Flash application for debug (local)**: monolithic debug binary.
- Clean variants: **Particle: Clean application (local)**, **Particle: Clean application & DeviceOS (local)**, **Particle: Clean application for debug (local)**. Use these for unexplained build errors.

Local flash needs USB. The device enters DFU mode automatically. Manual DFU: hold MODE (or SETUP), tap RESET, keep holding MODE until the status LED blinks magenta, then yellow. Release when it blinks yellow.

Compile and flash buttons appear in the upper right of `.cpp` and `.ino` files. By default they run local actions. Change with the **Compile Button Action** and **Flash Button Action** settings.

Build tasks: `cmd+shift+b` (Mac) or `ctrl+shift+b` (Linux and Windows).

Cloud build, local flash: after **Particle: Cloud Compile**, use **Particle: Launch CLI** and run `particle flash --local <file>.bin` with the device in DFU mode.

## Serial, CLI, and device access

- **Particle: Serial Monitor**: can reconnect automatically when the device restarts.
- **Particle: Launch CLI**: terminal with the Particle CLI. Use `particle help`. See [11-particle-cli.md](11-particle-cli.md).
- **Particle: Launch Compiler Shell**: direct `make` access.
- **Particle: Call Function** and **Particle: Read Variable**: device must be online and have registered the function or variable. See [06-cloud-functions-variables-events.md](06-cloud-functions-variables-events.md).
- Others: **Particle: Who Am I?**, **Particle: Audit Environment** (output for support requests; check for sensitive data before sharing), **Particle: Update CLI**, **Particle: Get Help**, **Particle: Show Welcome Screen**, **Particle: Add / Remove `particle` Command in PATH**.

## Libraries

- **Particle: Install Library** adds a library and its dependencies to `project.properties` and downloads source to `lib/`. Pin versions with syntax like `DS18B20@0.1.11`.
- **Particle: Find Libraries** searches by partial name.
- To remove: delete the entry in `project.properties` and its folder in `lib/`.
- Cloud compiles use versions listed in `project.properties`. Local compiles use the local copy in `lib/`.
- To use a modified community library in both build types, change `dependencies.` to `disabled_dependencies.` in `project.properties`.

## Debugging

- Gen 3 (modular builds; Device OS 4.0+ and 5.0+ depending on platform): use **Particle: Flash application & DeviceOS for debug (local)**, then start debugging from the Debug view with the Particle Debugger over a ribbon cable.
- Gen 2 (monolithic builds, e.g. Photon, P1, Electron): connect the debugger to D6 and D7, plus GND.
- Caveats:
  - On Gen 3 nRF52 devices, add `BLE.off();` at the top of `setup()` if the device blinks SOS during debugging.
  - `#pragma GCC optimize ("O0")` disables optimization for easier breakpoints.
  - Hardware breakpoints: 2 on P2 and Photon 2, 4 on nRF52840 Gen 3 devices.
  - Stepping into FreeRTOS requires `"rtos":"FreeRTOS"` in `launch.json`. Experimental.

## Settings and customization

- Path: Code > Preferences > Settings (Mac), or File > Preferences > Settings. Expand Extensions and select Particle.
- Options: Compile Button Action, Flash Button Action, Disable Welcome Screen, Disable Local Compiler Dirty Check, Enable Verbose Local Compiler Logging, Compile Defines, Custom Device OS Location.
- Themes: "Matter (by Particle)" and "Dark Matter (by Particle)".
- Keymaps: Vim, Sublime, Atom, IntelliJ, Visual Studio, Eclipse, Emacs (Preferences: Keymaps).

## Caveats

- Paths with spaces: on Windows, usernames or paths with spaces are converted to short paths. Mac and Linux do not currently support them.
- Build speed: the first local build after changing Device OS version or platform, or after a clean, takes many minutes. Windows builds are slower than Mac and Linux.
- 256K binary edge case: on Gen 3 devices upgrading from 3.0 or earlier to 3.1 or later over USB, an old 128K binary may keep running if the new binary is under 128K. Upgrade once with Device Restore USB first.
- Product devices: mark developer devices as "Mark As Development Device" in the console. Otherwise product firmware may overwrite your application after the device connects to the cloud.
- Library builds: local builds of library examples are not directly supported. Use `particle compile` through the CLI, or copy the example into `src/` temporarily.
- Source control: Workbench's Git support uses your desktop GitHub client. The page also covers cloning, forking, and mirroring Tracker Edge projects.
