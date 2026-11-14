# Serial (UART), SPI, I2C (Wire), CAN, PDM

Sources: Photon 2 datasheet (ports and pins), Device OS firmware reference (Serial, SPI, Wire, CAN, Mouse/Keyboard context).

## UART (Serial, Serial1, Serial2, Serial3)

Hardware ports, 3.3 V logic. Not RS-232 or 5 V compatible.

| Object | Port | Pins |
|---|---|---|
| `Serial1` | RTL UART_LOG | TX D8, RX D9 |
| `Serial2` | HS_UART0 | RTS D2, CTS D3, TX D4, RX D5 |
| `Serial3` | LP_UART | CTS D10, RX D16, TX D15, RTS D17 |

USB serial is `Serial` (USB CDC). The board table also lists `USBSerial1` and `Serial1` through `Serial5` on other generations.

Supported baud rates per the datasheet: 110, 300, 600, 1200, 2400, 4800, 9600, 14400, 19200, 28800, 38400, 57600, 76800, 115200, 128000, 153600, 230400, 380400, 460800, 500000, 921600, 1000000, 1382400, 1444400, 1500000, 1843200, 2000000, 2100000, 2764800, 3000000, 3250000, 3692300, 3750000, 4000000, 6000000.

### Serial API (from the firmware reference)

- `begin(unsigned long baud[, uint32_t config])`:
  - Gen 4 (Photon 2) supports 8N1 through 7E2.
  - Gen 3 supports only 8N1 and 8E1, plus flow control on D2/D3.
  - Gen 2 supports 1200-230400 baud, 7/8/9-bit modes, and LIN options (0.6.0+).
  - Calling `USBSerial1.begin()` causes a USB re-enumeration unless done from `STARTUP()`.
- `end()`.
- `available()`: USB buffer 256 bytes. UART 128 bytes on Gen 3, 64 or 128 on Gen 2.
- `availableForWrite()`.
- `acquireSerialBuffer()`, `acquireSerial1Buffer()`, `acquireSerial2Buffer()` (0.6.0+ / 3.2.0+): custom buffer sizes, minimum 64-65 bytes.
- `blockOnOverrun(bool)`: default `true` blocks the writer when the buffer overruns. `false` overwrites old data.
- `serialEvent()`, `serialEvent1()`, and so on: weak callbacks invoked between `loop()` calls. Long delays in `loop()` can drop characters.
- `peek()` and `peek(char*, size_t)` (6.5.0+): does not wait.
- `write()` and `write(buf, len)` (6.5.0+ bulk write).
- `read()` and `readBytes()`: default timeout 1000 ms. Bulk transfer since 6.5.0.
- `print()`, `println()`, `printf()`, `printlnf()`, `flush()`.
- `halfduplex(bool)`: single-wire on TX. Gen 2 hardware UARTs only.
- `isConnected()`: true when the host has the COM port open (USB).
- `lock()` / `unlock()`: USB serial objects only. UART objects have no WITH_LOCK support. Do not use inside `SINGLE_THREADED_BLOCK()`.
- Recommendation from the docs: use the `Log` API with `SerialLogHandler` instead of raw `Serial.print` for application logging. See the Log section in [12-gaps-and-unverified.md](12-gaps-and-unverified.md), since that section was not captured.

## SPI

Two ports, 3.3 V logic.

- SPI1 (RTL SPI1 peripheral, 25 MHz max): D2 MOSI, D3 MISO, D4 SCK, D5 SS.
- SPI (RTL SPI0 peripheral, 50 MHz max): D15 MOSI, D16 MISO, D17 SCK, D18 SS.
- Any pin can serve as a chip select. Use `digitalWrite()` for CS when using a non-SS pin.
- Device OS 5.3.1+ is recommended for correct speed and DMA timing.

### SPI API

- `begin(ss_pin)`: configures pins and sets the SS pin as output. Pass `PIN_INVALID` for none. You must control CS manually with `digitalWrite()`.
- `begin(SPI_Mode, ss_pin)` (0.5.0+): master or slave mode. Gen 3 slave mode is supported only on SPI1, max 8 MHz.
- `end()`: disables the bus, pin modes unchanged.
- `setBitOrder(order)`: `LSBFIRST` or `MSBFIRST`.
- `setClockSpeed(value, scale)`: picks the highest divider-based speed not exceeding the request. Gen 3: up to 32 MHz on SPI, 8 MHz on SPI1.
- `setClockDividerReference(value, scale)`: reference clock for dividers. Default is the system clock (64 MHz on Gen 3; 120 MHz on Gen 2, with SPI at 60 MHz and SPI1 at 30 MHz).
- `setClockDivider(divider)`: divider values 2 through 256 in powers of two. Default `SPI_CLOCK_DIV4`.
- `setDataMode(mode)`: `SPI_MODE0` through `SPI_MODE3`.
- `transfer(val)`: single-byte transfer, acquires the peripheral lock. Wrap loops in `beginTransaction()` / `endTransaction()`.
- `transfer(tx, rx, length, callback)`: DMA transfer. Buffers must be the same length. NULL callback makes it synchronous. Gen 3 (3.0.0+) can use flash-stored tx buffers. Callbacks run in ISR context.
- `transferCancel()` (0.5.0+): aborts DMA. The completion callback still fires.
- `onSelect(callback)` (0.5.0+): slave-select ISR handler. On Gen 3, DMA from this handler requires real RAM buffers (not NULL or flash).
- `available()` (0.5.0+): returns `int32_t` bytes received or transmitted in the current or last DMA transfer.
- `SPISettings` (0.6.2+): constructor takes clock, bit order, data mode.
- `beginTransaction(settings)` (0.6.1+): reconfigures the peripheral and acquires the lock. Returns negative on error. Do not call inside `SINGLE_THREADED_BLOCK`.
- `endTransaction()` (0.6.1+): releases the lock.
- From 6.4.0, SPI methods can be called from `PRE_STARTUP()`. In all versions, they can be called from `STARTUP()`.

## I2C (Wire)

- One port, `Wire`, on D0 (SDA) and D1 (SCL). 3.3 V only.
- Max 400 kHz. External pull-ups required (1.5K to 10K recommended).
- Internal pull-ups: Gen 2 has 40K weak on Photon/Electron and 2.1K on P1. Gen 3 has 13K. Gen 3 and P2 are not 5 V tolerant.
- Gen 3 and B-Series SoM can use `Wire1` on D2/D3. Tracker can use `Wire3` on RX/TX.

### Wire API

- `setSpeed(clockSpeed)`: must be called before `begin()`. Default 100 kHz, max 400 kHz. Gen 3 and Gen 4 accept arbitrary 10-99 kHz values from OS 6.3.5 onward.
- `stretchClock(stretch)`: clock stretching, slave mode only. Enabled by default. Call before `begin()`.
- `begin()` with no argument joins as master. `begin(address)` joins as slave.
- `end()` (0.4.6+): releases the bus pins.
- `isEnabled()`: returns bool.
- `requestFrom(address, quantity, stop)`: max 32 bytes unless you use `acquireWireBuffer()`. Returns byte count. Overload takes `WireTransmission` (1.5.0+).
- `reset()` (0.4.6+): attempts to recover a hung bus.
- `beginTransmission(address)`: also accepts `WireTransmission` (1.5.0+) with a timeout.
- `endTransmission(stop)`: returns status codes 0-7 (`SYSTEM_ERROR_*`).
- `write(value)` / `write(data, length)`: buffer is 32 bytes by default. Excess bytes are dropped.
- `available()`, `read()`, `peek()`: inherited from Stream.
- `lock()` / `unlock()`: needed for multi-threaded use. Not inside `SINGLE_THREADED_BLOCK`.
- `onReceive(handler)`: slave receive callback. Blocking calls such as `Particle.publish()` inside it can lock the device.
- `onRequest(handler)`: slave request callback, same warning.
- `acquireWireBuffer()` returns a config struct for custom buffers. `acquireWire1Buffer()` and `acquireWire3Buffer()` are the equivalents.

Known conflict: several boards have a built-in PMIC or fuel gauge on I2C. The docs describe how to disable the power manager when using Wire in slave mode. See [02-power-and-sleep.md](02-power-and-sleep.md).

## CAN (canbus)

- Scope: Gen 2 only (Photon, P1, Electron, E-Series). Tracker uses an external library. Other platforms need an external CAN chip.
- The Photon 2 datasheet and this API page do not list CAN as a Photon 2 feature. Treat CAN on Photon 2 as unsupported unless you confirm otherwise.

### CAN API

- `CANMessage` fields: `id`, `extended`, `rtr`, `len`, `data[8]`.
- `CANChannel(channel, rxQueueSize = 32, txQueueSize = 32)`: `CAN_D1_D2` on Photon and Electron; `CAN_C4_C5` on Electron only.
- `begin(baud, flags)`: common rates 50K-1M. `CAN_TEST_MODE` loops back transmitted messages.
- `end()`: disconnect from bus.
- `available()`: returns `uint8_t` count of queued received messages.
- `receive(message)`: non-blocking, returns bool.
- `transmit(message)`: queues a message. Returns false if the queue is full. With no other node on the bus, messages are never acknowledged and the queue fills.
- `addFilter(id, mask, type)`: up to 14 filters.
- `clearFilters()`: accept all messages.
- `isEnabled()`.
- `errorStatus()`: `CAN_NO_ERROR`, `CAN_ERROR_PASSIVE`, or `CAN_BUS_OFF`. Updated only during transmit attempts.

## PDM microphone

- Supported via the `Microphone_PDM` library on A0/D11 (CLK) and A1/D12 (DAT) only.

## Mouse and Keyboard (USB HID)

Covered in [09-data-types-and-utilities.md](09-data-types-and-utilities.md), since they share the USB port.

## Cross-references

- Pin map: [03-gpio-and-pin-map.md](03-gpio-and-pin-map.md).
- Ethernet, Wi-Fi, and BLE: [05-wifi-ble-network.md](05-wifi-ble-network.md).
