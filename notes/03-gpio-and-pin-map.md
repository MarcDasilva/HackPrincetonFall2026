# GPIO, Pin Map, ADC, PWM, DAC, Interrupts

Sources: Photon 2 datasheet (pin map, peripheral counts, boot pins), Device OS firmware reference (pin I/O, analog, PWM, interrupts, Timer).

## Peripheral counts

- 20 digital I/O
- 6 ADC inputs
- 2 SPI ports
- 1 I2C port
- 3 UART ports
- 1 USB
- 5 PWM outputs

## Logic and electrical

- Logic levels: VIH min 2.0 V, VIL max 0.8 V. Outputs are 3.3 V logic.
- Not 5 V tolerant. Do not connect 5 V signals directly.
- Drive strength:
  - Normal: 4 mA.
  - High: 12 mA. `pinSetDriveStrength` requires Device OS 5.5.0+.
- Total output drive across all pins: 200 mA.

## Pin-to-MCU map

| Arduino label | Alt name | MCU pin |
|---|---|---|
| D0 | A3 | PB[6] |
| D1 | A4 | PB[5] |
| D2 | | PA[16] |
| D3 | | PA[17] |
| D4 | | PA[18] |
| D5 | | PA[19] |
| D6 | SWCLK | PB[3] |
| D7 | SWDIO | PA[27] |
| D8 | TX | PA[7] |
| D9 | RX | PA[8] |
| D10 | WKP | PA[15] |
| D11 | A0 | PB[1] |
| D12 | A1 | PB[2] |
| D13 | A2 | PB[7] |
| D14 | A5 | PB[4] |
| D15 | MOSI | PA[12] |
| D16 | MISO | PA[13] |
| D17 | SCK | PA[14] |
| D18 | S3 | PB[26] |
| D19 | S4 | PA[0] |
| MODE | | PA[4] |
| RST | | CHIP_EN |

Note: D6 and D7 are the SWD debug pins. A6 is the battery sense (not on this table as a GPIO).

## Boot-time pin behavior

- TX (D8): if held low at boot, enters ISP flash download mode.
- D6: has a 40K pull-down at boot.
- D7: has a 40K pull-up at boot. If held low at boot, enters test mode.

Keep D7 and TX free of external pulls that fight these defaults during reset.

## Analog input (ADC)

- Six 12-bit single-ended inputs, 0 to 3.3 V. `analogRead()` returns 0-4095.
- Channels:
  - A0 (ADC_4, pin D11)
  - A1 (ADC_5, pin D12)
  - A2 (ADC_3, pin D13)
  - A5 (ADC_0, pin D14)
  - D0/A3 (ADC_2)
  - D1/A4 (ADC_1)
- A6 reads the battery voltage divider (VBAT_MEAS), 0 to 5 V scale. Use `analogRead(A6) / 819.2`.

## Analog output (DAC)

- The datasheet does not specify DAC channels for Photon 2.
- The firmware reference's DAC section is for Gen 2 DAC pins only: 0-4095 maps to 0-3.3 V. Do not assume Photon 2 has a DAC without checking the live page.

## PWM

- Five PWM outputs: A2/D13, A5/D14, D1/A4, MISO/D16, MOSI/D15.
- D0 has no PWM.
- `analogWrite()` default frequency is 500 Hz.
- `analogWriteResolution()` (0.6.0+) accepts 2 to 31 bits. Maximum frequency depends on resolution.
- Gen 4 (Photon 2, P2, M-SoM) PWM pins share one timer group. Pins with different frequencies in the same group conflict.
- Servo on Gen 4 requires 50 Hz PWM (see [09-data-types-and-utilities.md](09-data-types-and-utilities.md)).

## tone() and noTone()

- `void tone(uint8_t pin, unsigned int frequency, unsigned long duration = 0)`. Frequency range 20 Hz to 20 kHz.
- Gen 4 (P2, Photon 2, M-SoM): all PWM pins share one timer, so only one tone frequency at a time.
- `void noTone(uint8_t pin);` stops the tone on that pin.

## Digital I/O functions

- `pinMode(pin, mode)`: INPUT, OUTPUT, and the pull-up or pull-down variants. Pull values depend on device generation.
- `digitalWrite(pin, value)` and `digitalRead(pin)`.
- `pinGetMode()` / `getPinMode()` returns the current mode.
- Fast variants with no checks: `pinSetFast`, `pinResetFast`, `digitalWriteFast`, `pinReadFast`. Call `pinMode()` first. Allowed inside interrupt handlers.
- `shiftOut(dataPin, clockPin, bitOrder, val)` and `shiftIn(dataPin, clockPin, bitOrder)`: software bit-bang. `bitOrder` is MSBFIRST or LSBFIRST.
- `pulseIn(pin, value)` (0.4.7+): blocking, no interrupts. Returns pulse length in µs, or 0 after a 3-second timeout. Reliable range about 10 µs to 3 s. If the pin already sits at `value`, it waits for the opposite state first.

## Interrupts

`attachInterrupt(pin, handler, mode, priority, subpriority)`:
- Modes: `CHANGE`, `RISING`, `FALLING`.
- Overloads for plain functions and member functions.
- Priority defaults to 13 (lower number is higher priority). Subpriority defaults to 0.
- Returns bool. Call `pinMode()` first.

`detachInterrupt(pin)` returns bool. `interrupts()` and `noInterrupts()` enable and disable globally.

Pin limits (per the firmware reference, by generation):
- Gen 3: all A and D pins, up to 8 attached at once.
- Gen 2: shared EXTI-line restrictions.
- Gen 4 (Photon 2): no attachment limit, but HIBERNATE wake is restricted to the pins listed in [02-power-and-sleep.md](02-power-and-sleep.md).

ISR rules (violate these and the device misbehaves):
- No allocation, no Particle calls, no `delay()`, no logging, no mutexes, no `attachInterrupt`/`detachInterrupt`.
- Allowed: `pinSetFast`, `pinResetFast`, `analogRead`.
- `volatile` alone is not sufficient for data shared across threads. Use proper synchronization.
- Do not disable interrupts around mutex-taking code, Cloud calls, or allocation. Never return from a handler with interrupts disabled.

## Drive strength

- `pinSetDriveStrength(pin, strength)`: 2.0.0+ generally; RTL872x 5.5.0+ (Photon 2).
- Standard vs high drive current. The Gen 3 table is in the firmware reference.

## Wake-capable pins

- STOP and ULP: any GPIO can wake.
- HIBERNATE: only D2, D3, D4, D5, D10, D15, D16, D17. Full details in [02-power-and-sleep.md](02-power-and-sleep.md).

## Pins used by other subsystems

- Serial1 (UART_LOG): D8 TX, D9 RX.
- Serial2: D2 RTS, D3 CTS, D4 TX, D5 RX.
- Serial3: D10 CTS, D16 RX, D15 TX, D17 RTS.
- SPI1: D2 MOSI, D3 MISO, D4 SCK, D5 SS.
- SPI: D15 MOSI, D16 MISO, D17 SCK, D18 SS.
- I2C (Wire): D0 SDA, D1 SCL.
- PDM microphone: A0/D11 CLK, A1/D12 DAT.
- Ethernet on Wiz-net (when used): see the Ethernet pin reference in [05-wifi-ble-network.md](05-wifi-ble-network.md).

Pin reuse conflicts are real. If you use Serial2 for something, D2-D5 are gone for GPIO. Plan the map first.

## Timer class (software, not hardware)

- `Timer(period, callback, one_shot=false)`, plus a member-function overload.
- Methods: `start`, `stop`, `reset`, `changePeriod` (also starts a dormant timer), `dispose`, `isActive()`.
- ISR variants: `startFromISR`, `stopFromISR`, `resetFromISR`, `changePeriodFromISR`.
- Max 10 slots (free them with `dispose`).
- Callbacks run on a 1024-byte stack. Do not block or call Serial, publish, or cellular functions in them.

More in [08-time-timers-watchdogs-leds.md](08-time-timers-watchdogs-leds.md).
