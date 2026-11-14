# Power, Battery, PMIC, and Sleep

Sources: Photon 2 datasheet (power tables, wake rules), Device OS firmware reference (Power Manager, PMIC class, Cellular and Wi-Fi power notes).

## Current draw (Photon 2 datasheet)

| Mode | Min | Typical | Peak |
|---|---|---|---|
| Idle (MCU on, peripherals and radio off) | 21.4 mA | 23.2 mA | 23.8 mA |
| BLE advertising | 54.7 mA | 58.7 mA | 70.7 mA |
| Wi-Fi connected to AP | 54.6 mA | 60.5 mA | 265 mA |
| STOP, GPIO wake | 492 µA | 549 µA | 608 µA |
| STOP, timer wake | 500 µA | 552 µA | 598 µA |
| ULP, GPIO wake | 492 µA | 549 µA | 608 µA |
| ULP, timer wake | 500 µA | 552 µA | 598 µA |
| HIBERNATE, GPIO wake | (not given) | 114 µA | 249 µA |
| HIBERNATE, timer wake | (not given) | 114 µA | 253 µA |

Practical reading: Wi-Fi-connected peaks reach 265 mA, so the power source must handle bursts. The USB port's 500 mA minimum is tight for peaks. Use HIBERNATE for the lowest standby draw.

## Sleep and wake rules

- STOP and ULP modes:
  - Wake on any GPIO (rising, falling, or change).
  - Outputs keep their state.
- HIBERNATE mode:
  - Wakes only on D2, D3, D4, D5, D10, D15, D16, or D17.
  - Outputs go high-impedance.
  - D19/S4 has no internal pull resistor in HIBERNATE.
- Retained memory:
  - Preserved across sleep entry, OTA update, and `System.backupRamSync()` (Device OS 5.3.1+).
  - Saved every 10 seconds only on Device OS 5.3.1 to 5.8.0.
  - Not preserved across `System.reset()` or a hardware reset.
  - Storage: a dedicated flash page on 5.3.1 to 6.5.x. The flash file system on 6.6.0+.
- Sleep drops TCP connections. The TCPClient docs recommend `Particle.publish()` or webhooks over direct TCP for this reason.
- Cellular only: `Particle.disconnect()` and `Cellular.off()` can save power but cost reconnect time and data (see [07-cloud-connection-and-system-modes.md](07-cloud-connection-and-system-modes.md)).

## Battery and charging

- Battery voltage on Photon 2: `analogRead(A6) / 819.2`, from the `VBAT_MEAS` divider, valid for 0 to 5 VDC.
- No fuel gauge on Photon 2. Argon and Boron have different methods (see the FuelGauge notes in the firmware reference, summarized below).
- Charging:
  - LiPo connector is JST-PH, single cell, on-board charger.
  - Charge LED is on while charging and off when complete.
  - The CHG pin is unreliable on Photon 2.

## Power Manager (PMIC) configuration

Device OS manages the bq24195-class PMIC on boards that have one (B-Series, Argon, and others). The `SystemPowerConfiguration` API sets limits.

Configuration setters (defaults in parentheses):
- `powerSourceMaxCurrent()`: valid 100, 150, 500, 900, 1200, 1500 mA (900). Practically limited to about 1590 mA by hardware ILIM.
- `powerSourceMinVoltage()`: VIN minimum in mV (3880).
- `batteryChargeCurrent()`: charge current in mA (896). Effective current is the lesser of this and `powerSourceMaxCurrent()`.
- `batteryChargeVoltage()`: termination voltage in mV (4112).
- `socBitPrecision()` (5.9.0+): 18 for MAX17043 (default), 19 for MAX17048.
- `auxiliaryPowerControlPin()` (5.9.0+): controls the 3V3_AUX output. Requires a reset after changing.
- `interruptPin()` (5.9.0+): alternate PMIC or fuel-gauge interrupt pin.

SystemPowerFeature flags:
- `PMIC_DETECTION`: enables bq24195 detection on Wire. Avoid using D0/D1 as GPIO when set.
- `USE_VIN_SETTINGS_WITH_USB_HOST`: uses VIN limits even when a USB host is present.
- `DISABLE_CHARGING` (3.0.0+): persistent charging disable.
- `DISABLE`: Device OS stops applying any configuration. You must manage the PMIC yourself, including its watchdog.

Environment variables (6.5.0+):
- `PARTICLE_PMIC_INPUT_CURRENT`: valid 500-1500 mA. Out-of-range values are ignored.
- `PARTICLE_PMIC_CHARGE_CURRENT`: valid 512-1500 mA. Applied at boot or on `setPowerConfiguration()`, not live.

B-Series SoM note: uses D0/D1 (I2C) and A6 (PM_INT). Disable system power configuration if you need those pins for GPIO.

## PMIC class (bq24195 register map)

Constructor: `PMIC(bool _lock=false);` Pass `true` for stack locals. Use from `PRE_STARTUP()` only with a local object.

Methods (grouped by register):
- Init and status:
  - `bool begin();` initializes Wire if needed.
  - `byte getVersion();` returns 0x23 for bq24195/bq24195L.
  - `lock()` / `unlock()` for thread safety between system and user threads.
- REG00 input source:
  - `enableBuck()` / `disableBuck()` / `isBuckEnabled()`.
  - `setInputCurrentLimit`, `getInputCurrentLimit`.
  - `setInputVoltageLimit` (3880-5080 mV, 80 mV steps, default 4360), `getInputVoltageLimit`.
- REG01 power-on configuration:
  - `enableCharging()` / `disableCharging()` / `isChargingEnabled()`.
  - `enableOTG()` / `disableOTG()`. The docs say Particle devices should never enable OTG.
  - `resetWatchdog`, `setMinimumSystemVoltage` (3000-3700 mV, default 3500), `getMinimumSystemVoltage`, `readPowerONRegister`, `reset()`.
- REG02 charge current:
  - `setChargeCurrent` (512-4544 mA on bq24195, 64 mA steps), `getChargeCurrent`, `getChargeCurrentValue`.
- REG03 precharge and termination:
  - `setPreChargeCurrent()` (fixed 256 mA, no parameter), `getPreChargeCurrent`.
  - `setTermChargeCurrent` (128-2048 mA, default 256), `getTermChargeCurrent`.
- REG04 charge voltage:
  - `setChargeVoltage` accepts 4112 (default) or 4208. Do not use 4208 on Device OS 0.4.8 or 0.5.0.
  - `getChargeVoltageValue`, `getChargeVoltage`, `getRechargeThreshold`, `setRechargeThreshold` (100 or 300 mV).
- REG05 charge timer:
  - `readChargeTermRegister`, `disableWatchdog`, `setWatchdog(byte)` (0 = off, 1 = 40 s default, 2 = 80 s, 3 = 160 s).
  - `enableSafetyTimer`, `disableSafetyTimer`.
- REG06 thermal regulation:
  - `setThermalRegulation()` (fixed 120 °C), `getThermalRegulation`.
- REG07 miscellaneous:
  - `readOpControlRegister`, `enableDPDM`, `disableDPDM`, `isInDPDM`.
  - `enableBATFET` / `disableBATFET` / `isBATFETEnabled`. Disabling BATFET is the basis of shipping mode; the device powers off if no other source is present.
  - `safetyTimer()`, charge and battery fault interrupt enable and disable.
- REG08 system status: `getVbusStat`, `getChargingStat`, `getDPMStat`, `isPowerGood`, `isHot`, `getVsysStat`.
- REG09 fault: `isWatchdogFault`, `getChargeFault`, `isBatFault`, `getNTCFault` (5 = cold, 6 = hot).
- Raw access: `getSystemStatus()` returns raw REG08. `getFault()` returns raw REG09; reading clears it, so read twice for the current state.

## FuelGauge (Boron, B-Series, Tracker, Electron, E-Series)

- `getVCell()`, `getSoC()`, `getNormalizedSoC()`: return `float`, or -1.0 on read failure. Normalized SoC reads 100% at full charge.
- Also present with signatures only: `getVersion()`, `getCompensateValue()`, `getAlertThreshold()`, `setAlertThreshold()`, `getAlert()`, `clearAlert()`, `reset()`, `quickStart()`, `sleep()`, `wakeup()`.

## Argon battery note

- Battery voltage: `analogRead(BATT) * 0.0011224`, plus the CHG pin and the `hasVUSB()` register check.

## Cross-references

- Pin-level details for D2-D5 and D10/D15-D17 wake sources: [03-gpio-and-pin-map.md](03-gpio-and-pin-map.md).
- Datasheet power input rules: [01-hardware-datasheet.md](01-hardware-datasheet.md).
