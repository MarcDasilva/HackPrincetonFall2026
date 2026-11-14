# Data Types, Ledger, NFC, USB HID, Servo, Utilities

Source: Device OS firmware reference (Buffer, EventData, Variant, VariantArray, VariantMap, Map, Vector, Ledger, NFC, Mouse, Keyboard, Servo, IPAddress, BLE types). Retrieved 2026-11-13. Partial: the pages were truncated near the end of RGB and Buffer. Items past the RGB section (for example rest of Buffer, RGB mirror details beyond `mirrorDisable`, and any later sections) are not captured. See [12-gaps-and-unverified.md](12-gaps-and-unverified.md).

## Buffer (6.2.0+)

- Constructors: pre-allocated by size, or copied from data and size. Wraps `std::vector<char>`.
- Limitation: Buffers in a `Variant` cannot be converted to or from JSON on the device.
- `data()`: `char*` (non-const) or `const char*` to the internal buffer. Binary, not null-terminated.
- `size()`, `isEmpty()`.
- `resize(size_t)`: returns false if growing fails, leaving size unchanged.
- `capacity()`, `reserve(size_t)`: reserve must be larger than current capacity. `trimToSize()` shrinks, never grows.
- `toHex()` (String and pointer/size overloads): hex-encodes. The pointer form null-terminates only if the size allows.
- `fromHex()` (static; String, c-string, pointer/size): decodes hex. With pointer/size, the length excludes any null terminator.
- `operator==` and `operator!=`: compare size and bytes.

## EventData

- 6.3.0+. An alias for `Variant`, used with `CloudEvent` subscriptions.

## Variant (6.1.0+)

- `set(key, Variant)`. Binary data uses `Buffer` (6.2.0+).
- Types: `NULL`, `BOOL`, `INT`, `UINT`, `INT64`, `UINT64`, `DOUBLE`, `STRING`, `BUFFER`, `ARRAY`, `MAP`.
- Constructors: overloads for primitives, `String`, `Buffer`, `VariantArray`, `VariantMap`. `const char*` and `String` are UTF-8 text only.
- `value<T>()`: returns a reference to the held value. Wrong type is undefined behavior.
- Conversion styles:
  - `value()`: no conversion.
  - `as()`: converts in place. Compile error if unsupported.
  - `to()`: returns a converted copy, leaves the variant unchanged.
- Type checks: `type()` and `isNull()`, `isBool()`, `isInt()`, `isUInt()`, `isInt64()`, `isUInt64()`, `isDouble()`, `isNumber()`, `isString()`, `isBuffer()`, `isArray()`, `isMap()`.
- Conversions (copies): `toBool`, `toInt`, `toUInt`, `toInt64`, `toUInt64`, `toDouble`, `toString`, `toBuffer`, `toArray`, `toMap`. Most have an optional `bool& ok` overload. `toArray` and `toMap` succeed only on matching types.
- In-place: `asBool`, `asInt`, `asUInt`, `asInt64`, `asUInt64`, `asDouble`, `asString`, `asBuffer` return a modifiable reference after converting. `asArray` and `asMap` do not convert and assert on mismatch.
- `toJSON()`: serializes an array or map to `String`.
- `Variant::fromJSON()` (static; c-string or `JSONValue`) builds a Variant.

### VariantArray and VariantMap

- `VariantArray` is `Vector<Variant>`. Operations: `append`, `prepend`, `insertAt`, `removeAt`, `at` (returns a copy).
- `VariantMap` is `Map<String, Variant>`. Operations: `set`, `remove`, `get`, `has`.
  - `get()` returns a copy. Returns a null variant if the key is missing or the variant is not a map.
  - `set()` converts the variant to a map if needed.

## Map template

- Constructors: default, initializer list, copy.
- Methods: `set`, `get` (with and without default), `has`, `find`, `begin`, `end`, `erase`, `remove`, `clear`, `size`, `isEmpty`, `operator[]`.
- `operator[]` creates missing entries. Memory exhaustion causes a SOS panic. `set()` reports failure by return value instead, so prefer `set()` on constrained memory.
- The `isEmpty()` prototype in the docs contains a typo (`ool`).

## Vector template (0.6.1+)

- A lighter alternative to `std::vector` that avoids linking it.
- Constructors: default, count, count with value, initializer list, copy. Copying `Vector<void*>` copies pointers, not their targets.
- `append`, `prepend`, `insert`: value, repeated value, array, and vector overloads. All return bool.
- `removeAt`, `removeOne`, `removeAll`, `takeFirst`, `takeLast`, `takeAt`. `takeFirst` and `takeLast` require a non-empty vector.
- `first`, `last`, `at`, `operator[]`: no bounds check. `operator[]` cannot grow the vector.
- `indexOf`, `lastIndexOf`, `contains`: return -1 when not found.
- `size`, `isEmpty`, `clear`, `begin`, `end`, iterator `insert` and `erase`.
- Docs have duplicate headings: the iterator `erase` section is titled `insert(ConstIterator pos, T value)`, and the `clear()` section is titled `isEmpty()`. Read the code, not the headings.

## Ledger (6.1.0+)

Cloud-backed key-value storage that syncs between device and cloud. Ledger types and scopes are defined in the cloud, not on the device.

- `Particle.ledger(name)`: asynchronous.
- `set(data, mode)`: saves locally at once; syncs later. `SetMode::REPLACE` or `MERGE`.
- Sync timing: the first change syncs immediately, then a 5-second cooldown restarts on each change. Maximum delay 30 seconds.
- `get()`: does not block. May return empty data before the first sync.
- `lastUpdated()`, `lastSynced()`, `dataSize()`, `name()`, `scope()`, `isWritable()`.
- `LedgerScope`: `UNKNOWN`, `DEVICE`, `PRODUCT`, `OWNER`.
- `onSync()` (two overloads): C function with `arg`, or `std::function`.
- `remove(name)` and `removeAll()` are static. The device must be disconnected from the cloud.

### LedgerData

- Constructors from `Variant` (must be a map) or initializer list.
- Map-style: `set()`, `remove()`, `get()` (copy), `operator[]` (reference, creates missing entries), `has()`, `isEmpty()`.

## NFC

- Gen 3 devices can only emulate an NFC tag. Gen 2 and P2 or Photon 2 do not support NFC. NFC requires Device OS 1.3.1+.
- `NFC.on(callback)` (callback optional), `NFC.off()`, `NFC.update()`.
- Callback signature: `void nfcCallback(nfc_event_type_t, nfc_event_t*, void*)`. Events: `NFC_EVENT_FIELD_ON`, `NFC_EVENT_FIELD_OFF`, `NFC_EVENT_READ`.
- Callbacks run at interrupt time. Do not allocate, call `Particle.publish()`, `delay()`, or logging.
- Payloads (mutually exclusive): `setText(text, encoding)`, `setUri(uri, NfcUriType)`, `setLaunchApp(package)` (Android only), `setCustomData(Record&)`. Each record is limited to 988 bytes.
- `Record`: `setTnf()`, `setType()`, `setId()`, `setPayload()`.

## Mouse (USB HID, 0.6.0+)

Relative and absolute pointer, 3 buttons, wheel. Supported on P2 and Photon 2 (5.4.0+) and Gen 2 (0.6.0+). Not supported on Boron, B-Series SoM, Argon, Tracker, or E404X.

- `Mouse.begin()`: causes a quick USB disconnect and reconnect. Use `STARTUP()` to avoid this. Available on P2 and Photon 2 since 5.4.0.
- `Mouse.end()`: disables Mouse. Calling it alone does not disconnect, but disabling both Mouse and Keyboard does.
- `move(x, y, wheel = 0)`: relative. `x` and `y` are `int16_t` in [-32767, 32767]. `wheel` is `int8_t` in [-127, 127].
- `moveTo(x, y)`: absolute. Default range [0, 32767] on both axes, origin top-left. Becomes screen-based after `screenSize()`.
- `scroll(wheel)`: `int8_t` in [-127, 127].
- `click(button = MOUSE_LEFT)`: press and release. Accepts `MOUSE_LEFT`, `MOUSE_RIGHT`, `MOUSE_MIDDLE`, or ORed combinations.
- `press(button)` holds until `release(button)`. `release(MOUSE_ALL)` releases everything.
- `isPressed(button = MOUSE_LEFT)`: bool.
- `screenSize(width, height, margins...)`: maps the 0-32767 `moveTo()` range to screen pixels. Margins are floats in percent.
- `enableMoveTo(state)`: enables or disables absolute (digitizer) movement. Changing at runtime causes a USB reconnect unless done in `STARTUP()`. On Linux X11, absolute and relative cannot coexist, so `enableMoveTo(false)` is needed for `move()`.

## Keyboard (USB HID, 5.4.0+ on P2 and Photon 2)

Same support matrix as Mouse. Not on Boron, B-Series, Argon, Tracker, E404X.

- `Keyboard.begin()`: enables HID stack. Same reconnect behavior as Mouse. No parameters.
- `Keyboard.end()`: disables. Reconnects without HID if Mouse is also disabled.
- `write(ch)`: types an ASCII character via a conversion table. Uppercase uses SHIFT.
- `click(k, modifiers = 0)`: press and release a USB HID keycode with optional modifiers. Keycodes `0x04` to `0xDD`.
- `press(k, modifiers = 0)`: holds a key. Up to 8 regular keys at once. Modifiers do not count toward that limit.
- `release(k, modifiers = 0)`.
- `releaseAll()`.
- `print()`, `println()`, `printf()`, `printlnf()`: as for Serial.

## Servo

- `attach()`, `write()`, `writeMicroseconds()` (default range 544 to 2400 µs), `read()`, `attached()`, `detach()`, `setTrim()`.
- Attachable only to timer-capable pins, which vary by device. The destructor detaches from 2.0.0 onward.
- On Gen 4 devices (P2, Photon 2, M-SoM), PWM must be set to 50 Hz for Servo to work.

## TCP and UDP

Covered in [05-wifi-ble-network.md](05-wifi-ble-network.md).

## IPAddress

- Constructors from 32-bit integer or byte array, indexing, comparisons, assignment, printing.

## BLE types

Covered in [05-wifi-ble-network.md](05-wifi-ble-network.md). Includes `BleAddress`, `BleAddressType`, `BleAdvertisingData`, `BleAdvertisingDataType`, `BleScanResult`, `BleScanFilter`, `iBeacon`.

## Stream helpers

- `Serial`, `Wire`, and others inherit from `Stream`. Common methods: `available()`, `read()`, `peek()`, `readBytes()`, `write()`, `print()`, `println()`. See [04-serial-spi-i2c-can.md](04-serial-spi-i2c-can.md).
