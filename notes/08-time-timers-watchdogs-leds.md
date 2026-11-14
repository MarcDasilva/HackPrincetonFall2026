# Time, Timers, Watchdogs, LEDs, Math

Source: Device OS firmware reference (Time, Chrono literals, Timer, Watchdog hardware and application, LEDStatus, LEDSystemTheme, RGB, Math). Retrieved 2026-11-13.

## Time (calendar and clock)

Clock functions:
- `millis()`: `system_tick_t`. Overflows after about 49 days. Use `System.millis()` for 64-bit.
- `micros()`: `unsigned long`. Overflows at the 32-bit maximum.
- `delay(ms)`: accepts milliseconds or chrono literals. Avoid long delays in `loop()` when threading is off.
- `delayMicroseconds(us)`: accepts microseconds or chrono literals (1.5.0+).

Chrono literals (1.5.0+): units `us`, `ms`, `s`, `min`, `h`. Each API has a minimum unit, and `delay()` rejects microseconds at compile time.

Calendar getters (each takes an optional UTC `time_t`):
- `Time.hour()`, `Time.hourFormat12()`, `Time.isAM()`, `Time.isPM()`, `Time.minute()`, `Time.second()`, `Time.day()`, `Time.weekday()` (1 = Sunday), `Time.month()`, `Time.year()`.
- Local timezone and DST are applied internally. Pass UTC to avoid a double offset.

Time values:
- `Time.now()`: `time32_t` UTC.
- `Time.local()`: `time32_t` in the configured timezone.

Timezone and DST:
- `Time.zone(float)`: -12.0 to 14.0 hours. No DST handling.
- `Time.isDST()`.
- `Time.getDSTOffset()`: default +1.0.
- `Time.setDSTOffset(float)`: 0.0 to 2.0.
- `Time.beginDST()` and `Time.endDST()`.
- DST is never applied automatically. You must call these yourself.

Setting time:
- `Time.setTime(time_t)`: overrides the cloud time until the next handshake.
- `Time.isValid()`: true after a manual set, a cloud sync, or RTC retention (Gen 2). In AUTOMATIC mode with threading disabled, it can block when connected and not yet synced.

Formatting:
- `Time.timeStr()`.
- `Time.format(time, spec)`: default, ISO 8601, or strftime-style spec.
- `Time.setFormat()` / `Time.getFormat()`.
- Format input must be UTC without an offset.

## Timer (software timers)

- `Timer(period, callback, one_shot = false)`, plus a member-function overload with an instance reference (0.4.9+).
- Methods: `start()`, `stop()`, `reset()`, `changePeriod()` (chrono overload 1.5.0+; also starts a dormant timer), `dispose()` (frees one of up to 10 slots), `isActive() const` (0.5.0+).
- ISR variants: `startFromISR()`, `stopFromISR()`, `resetFromISR()`, `changePeriodFromISR()`.
- Callbacks run on a 1024-byte stack. Do not block, and do not call `Serial.print`, `Particle.publish`, or cellular functions in them.
- Changing the period resets the timer.

## Watchdog (hardware, 5.3.0+)

- `Watchdog.init(WatchdogConfiguration)`: must be called while not running.
  - Maximum timeout: 131,071,999 ms on nRF52. 8,190,000 ms on RTL872x (Photon 2).
  - Recommended minimum around 30 seconds.
- `Watchdog.start()`, `Watchdog.stop()`, `Watchdog.refresh()`.
  - `stop()` is not available on nRF52.
  - `refresh()` must be called more often than the timeout.
- `capabilities(...)`: `NOTIFY`, `NOTIFY_ONLY`, `RECONFIGURABLE`, `STOPPABLE`, `SLEEP_RUNNING`, `DEBUG_RUNNING`. Availability varies by platform.
- `onExpired(...)`: runs in ISR context. Only setting a retained variable is safe. The Particle team recommends not using it.

## ApplicationWatchdog (software, 0.5.0+)

```cpp
ApplicationWatchdog(timeout, fn, stack_size = 512);
```

- FreeRTOS-based software watchdog. Recommended stack size at least 1536 bytes.
- `ApplicationWatchdog::checkin()`: resets the count during long loops. `Particle.process()` calls it internally.
- The handler should only call `System.reset()` (for example with `RESET_NO_WAIT`).
- `waitFor()` does not feed it.
- The Particle team recommends the hardware watchdog instead.

## LED status

### LEDStatus class (0.6.1+)

- Constructors: four overloads taking color, pattern, speed or period, and priority. Defaults: `RGB_COLOR_WHITE`, `LED_PATTERN_SOLID`, `LED_PRIORITY_NORMAL`. New instances start inactive.
- Accessors: `setColor`/`color`, `setPattern`/`pattern`, `setSpeed` (resets period to that speed and pattern's default), `setPeriod`/`period` (ms), `setPriority`/`priority`.
- A new priority takes effect only on the next `setActive()`.
- On/off: `on()`, `off()`, `toggle()`, `isOn()`, `isOff()`.
- Activation: `setActive(bool = true)`, `setActive(LEDPriority)` (sets priority, then activates), `isActive() const`.
- Priority defaults for system signals:
  - Gen 3: breathing cyan default is `LED_PRIORITY_NORMAL`. Override with `LED_PRIORITY_IMPORTANT`.
  - Gen 2: default is `LED_PRIORITY_BACKGROUND`. Override with `NORMAL` or `IMPORTANT`.
- Custom patterns: subclass `LEDStatus`, pass `LED_PATTERN_CUSTOM`, and override `update(system_tick_t ticks)`. `update()` may run inside an ISR. Do not block there.

### LEDSystemTheme (0.6.1+; PRE_STARTUP from 6.4.0)

- `LEDSystemTheme()` initializes from current system settings.
- Per-signal: `setColor`/`color`, `setPattern`/`pattern`, `setSpeed`, `setPeriod`/`period`, `setSignal` (several at once).
- `apply(bool save = false)`: applies, optionally persists.
- `static restoreDefault()`: restores factory theme.
- From `PRE_STARTUP()`, the object must be local, not global.

### LEDSignal enum

Lists system signals: network off/on/connecting/DHCP/connected, cloud connecting/handshake/connected, safe mode, listening mode, DFU mode, power-off. Each has a priority and default pattern. DFU-mode customization is not supported because of bootloader flash limits.

### Enums

- `LEDPriority` (low to high): `BACKGROUND`, `NORMAL`, `IMPORTANT`, `CRITICAL`. On ties, system signals take precedence.
- `LEDPattern`: `SOLID`, `BLINK`, `FADE`, `CUSTOM`.
- `LEDSpeed`: `SLOW`, `NORMAL`, `FAST`.

## RGB LED

- `RGB.control(true)`, `RGB.controlled()`: take manual control of the on-board LED. `RGB.color()` takes three values or a packed `uint32_t`.
- `RGB.brightness()`: set and get.
- `RGB.onChange()`: handlers run about 1000 times per second. Do not call logging, serial, or publish functions there.
- Colors are 32-bit `0x00RRGGBB`. Named constants include blue, green, cyan, red, magenta, yellow, white, gray, and orange.
- `STARTUP(RGB.mirrorTo(pinr, ping, pinb, invert, bootloader))` (0.6.1+): mirrors the on-board LED to three PWM-capable pins. `invert` selects common-anode (default is common-cathode).
  - Do not pass `bootloader = true` from `STARTUP()`.
  - `RGB.mirrorDisable()` (0.6.1+) disables mirroring. With `bootloader = true` (default), it also clears the DCT config.

## Math

- `min()`, `max()`, `abs()`: avoid side effects in arguments. Macros may evaluate arguments more than once.
- `constrain(x, a, b)`: clamps to a range.
- `map(value, fromStart, fromEnd, toStart, toEnd)`: `int` and `double` overloads. Integer math truncates, does not clamp, and can reverse ranges.
- `math.h` (newlib) is available. The docs' section on it was truncated.

## Cross-references

- Interrupt and timer ISR rules: [03-gpio-and-pin-map.md](03-gpio-and-pin-map.md).
- Time sync with cloud: [07-cloud-connection-and-system-modes.md](07-cloud-connection-and-system-modes.md).
