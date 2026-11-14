# Wi-Fi, BLE, Ethernet, Network, Tether, TCP/UDP

Sources: Device OS firmware reference (WiFi, BLE, Ethernet, Network, NetworkInterfaceConfig, Tether, TCP/UDP, SoftAP sections) and Photon 2 datasheet (antenna and radio specs).

## Availability

- Photon 2: Wi-Fi (802.11 a/b/g/n) and BLE 5. Ethernet is available via the wiznet pin remap (see below).
- Cellular devices (Boron, B-Series, Tracker, E-Series, Electron) do not have the WiFi class.
- Tracker SoM has Wi-Fi for geolocation only.

## WiFi class

### Power and lifecycle

- `WiFi.on()` / `WiFi.off()`. `off()` saves power. Call `Particle.disconnect()` first, and use it only in SEMI_AUTOMATIC or MANUAL mode.
- Gen 3 devices before Device OS 2.0.0 required `WiFi.on()` before `connect()`. Not needed on Photon 2.
- `WiFi.disconnect()`: since 6.6.0, disconnects the cloud first if it uses this interface, then resumes the session on reconnect.

### Connecting

- `WiFi.connect(unsigned flags = 0)`: without stored credentials, enters listening mode unless `WIFI_CONNECT_SKIP_LISTEN` is passed (0.4.5+).
- On Argon since 1.5.0, a scan selects the strongest matching access point.
- `WiFi.connecting()` and `WiFi.ready()`. `ready()` is true once an IP address is assigned.

### Credentials

- `setCredentials()` has overloads: SSID only; SSID and password; SSID, password, and security; a full overload with lengths; and `WiFiCredentials`-based overloads.
- Storage limits: 10 credentials on P2, Photon 2, and Argon. 5 on Photon and P1.
- Password: up to 64 seven-bit ASCII characters. Longer input is truncated.
- WPA Enterprise is supported only on Photon and P1 (0.7.0+), via `WiFiCredentials`.
- Hidden SSIDs: supported since 5.5.0 on P2, Photon 2, and M-SoM, via `WiFiCredentials::setHidden()`. Not supported on Argon.
- `setCredentials()` returns true on success. Wi-Fi must be on.
- `getCredentials(WiFiAccessPoint* results, size_t count)` (0.4.9+): returns the number of stored networks. Passwords are not returned.
- `WiFiAccessPoint` fields: `size`, `ssid[33]`, `ssidLength`, `bssid[6]`, `security`, `cipher`, `channel`, `maxDataRate`, `rssi`.
- `clearCredentials()` returns true on success. `hasCredentials()` returns true if any are stored.

### Scanning

- `scan()` has two forms: fill an array (returns count) or a callback (optionally with an instance pointer).
- Caveat: array form silently drops results beyond capacity.

### Addresses and identity

- `macAddress(uint8_t*)` writes the device MAC.
- `SSID()` returns the connected network name as `char*`.
- `BSSID(uint8_t*)` writes the access point MAC.
- `localIP()`, `subnetMask()`, `gatewayIP()`, `dnsServerIP()`, `dhcpServerIP()`. `dnsServerIP()` and `dhcpServerIP()` need `Particle.process()` after connecting. `dhcpServerIP()` applies to Gen 2.
- `resolve(name)`: returns `IPAddress`, blank on failure.
- `ping()` (6.3.0+): overloads taking `IPAddress` or a hostname, with tries and timeout. Returns packet count or a negative error. Default timeout 4000 ms. Photon and P1 have only the basic overloads.

### Signal

- `RSSI()` (0.8.0+) returns `WiFiSignal`.
  - Signal value range is -127 to -1 dBm. Positive values are error codes (1 chip error, 2 timeout).
  - Cast to `(int8_t)` when passing to printf-style functions.
- `WiFiSignal` methods:
  - `getStrength()`: percentage 0.0 to 100.0.
  - `getQuality()`: percentage 0.0 to 100.0.
  - `getStrengthValue()`: dBm, -90 to 0.
  - `getQualityValue()`: SNR in dB, 0 to 90.

### Antenna

- `selectAntenna(WLanSelectAntenna_TypeDef)`: `ANT_AUTO`, `ANT_INTERNAL`, or `ANT_EXTERNAL`. Returns 0 on success.
- Default: `ANT_INTERNAL` if none selected.
- Persistent: survives power loss and safe mode. Not cleared by credential reset.
- Requires Device OS 5.3.2+ on P2, Photon 2, and M-SoM.
- Argon has no Wi-Fi antenna switch.
- Set it in `STARTUP()` so it applies at boot.
- `getAntenna()` returns the current mode.

### Country code (regulatory channel plan)

- `setCountryCode()` / `getCountryCode()`: 5.1.0+, Photon 2, P2, and M-SoM only. Photon and P1 can set DCT to `WLAN_CC_JP` instead.
- Default: US channel plan, which disables channel 12.
- Stored at DCT offset 1758, two bytes, big-endian. Persists across flashing and credential clearing.
- Must be set before connecting.
- Other ways to set: DFU mode with `dfu-util -a 1`, or the web tool. Gen 3 and Gen 4 DCT is file-based, so SWD or JTAG is impractical.
- Codes: `WLAN_CC_UNSET` (0x0000), `US` (0x5553), `EU` (0x4555), `JP` (0x4A50), `CA` (0x4341), `MX` (0x4D58), `GB` (0x4742), `AU` (0x4155), `KR` (0x4B52), `WORLD` (0xFFFE), `MAX` (0xFFFF).
- `getCountryCode()`: returns the code if non-negative, or an error if negative.

### Static IP (Photon and P1 only)

- `setStaticIP()`, `useStaticIP()`, `useDynamicIP()`. Addresses persist across application and safe mode.
- Newer devices use `NetworkInterfaceConfig` instead (see below).
- `setHostname()` / `hostname()`: Photon and P1, 0.7.0+. Default is the device ID.

### Listening mode

- `listen(begin = true)`: accepts Wi-Fi credentials over USB serial and Bluetooth. Blocks application code unless threading is used.
- `listening()`: true in listening mode. Always false without threading. System thread is always enabled in 6.2.0+.
- `setListenTimeout(uint16_t)`: seconds, 0 disables (default 0). Changing it during an active timer restarts it. Chrono literals since 1.5.0 (for example `5min`).
- `getListenTimeout()`: seconds.
- Listening uses a SoftAP on Photon, and BLE on Argon.

### WiFiCredentials class

- Constructors: default (open), `WiFiCredentials(SecurityType)`, and `WiFiCredentials(const char* ssid, SecurityType = UNSEC)`.
- Chainable setters:
  - `setSsid`
  - `setSecurity`: `SecurityType`
  - `setCipher`: `WLanSecurityCipher`
  - `setPassword`: up to 64 characters. For PEAP, this is the user password.
  - `setHidden` (5.5.0+)
  - `setValidate` (5.8.0+): tests the network before saving. May disconnect the current connection.
  - `setChannel`
  - Enterprise (Photon and P1 only): `setEapType`, `setIdentity`, `setOuterIdentity`, `setClientCertificate`, `setPrivateKey`, `setRootCertificate`. Certificates are PEM. Multiple root certificates can be concatenated.
- Enums:
  - `WLanEapType`: `WLAN_EAP_TYPE_PEAP` (PEAPv0/EAP-MSCHAPv2), `WLAN_EAP_TYPE_TLS` (EAP-TLS).
  - `SecurityType`: `UNSEC`, `WEP`, `WPA`, `WPA2`, `WPA_ENTERPRISE`, `WPA2_ENTERPRISE`.
  - `WLanSecurityCipher`: `WLAN_CIPHER_NOT_SET`, `WLAN_CIPHER_AES`, `WLAN_CIPHER_TKIP`, `WLAN_CIPHER_AES_TKIP`.

## BLE

Scope: Photon 2, P2, and Gen 3 devices (OS 1.3.1+). Gen 2 does not support BLE. Mesh and A2DP audio are not supported.

### Radio and lifecycle

- `BLE.on()`, `BLE.off()`, `BLE.begin()`, `BLE.end()`. The radio is on by default in `SYSTEM_MODE(AUTOMATIC)`.
- `BLE.address()` returns this device's `BleAddress`.
- `BLE.setTxPower(int8_t)` and `BLE.txPower(int8_t*)`: valid -20, -16, -12, -8, -4, 0, 4, 8 dBm. Default 0.
- `BLE.selectAntenna(BleAntennaType)`: persistent. B-Series SoM has no internal antenna. On P2 and Photon 2 this also affects Wi-Fi. An `EXTERNAL` macro naming conflict may need `#undef EXTERNAL`.

### Advertising (peripheral role)

- `BLE.advertise(advData, scanResponse)`: continuous advertising. Returns 0 on success. Not allowed in listening mode.
- `BLE.advertise(iBeacon)`: advertises as an iBeacon.
- `BLE.advertise()`: resumes with previously set data.
- `BLE.stopAdvertising()`: stops. Resumes automatically after a disconnect.
- `BLE.advertising()`: bool.
- `BLE.getAdvertisingData()` / `setAdvertisingData()`.
- `BLE.setAdvertisingInterval(interval)`: units 0.625 ms, range 32-16383 (20 ms to 10.24 s). Default 160 (100 ms).
- `BLE.setAdvertisingTimeout(timeout)`: units 10 ms. 0 means indefinite (default).
- `BLE.setAdvertisingType(type)`: values 0-6. Default 0 (connectable, scannable, undirected).
- `BLE.setAdvertisingPhy(phy)` (3.1.0+): `BLE_PHYS_AUTO`, `BLE_PHYS_1MBPS`, `BLE_PHYS_CODED`. Coded PHY not available on P2 or Photon 2.
- `BLE.getScanResponseData()` / `setScanResponseData()`: up to 31 bytes.
- Connection callbacks: `BLE.onConnected()` and `BLE.onDisconnected()` take `(const BlePeerDevice&, void* context)`. Since 3.0.0 also accept member functions or lambdas.

### Advertising payload (BleAdvertisingData)

- Limit 31 bytes (`BLE_MAX_ADV_DATA_LEN`) including per-block overhead.
- Methods: constructor, `clear()`, `remove()`, `set()`, `append(type, buf, len, force)` (replaces existing blocks of the same type unless `force`).
- `appendCustomData()`: one manufacturer block, max 26 bytes including company ID. Up to 255 bytes with coded PHY (3.2.0+).
- `appendLocalName()`, `appendServiceUUID()`: only one 128-bit UUID fits alongside a name.
- Read side: `get(type, buf, len)`, `get(buf, len)`, `length()`, `operator[]`, `deviceName()`, `serviceUUID()` (up to 14 16-bit UUIDs), `customData()`, `contains(type)`.
- FLAGS is inserted automatically if omitted. Value 0x06 (LE-only general discovery) is the common choice.

### Characteristics and services (GATT)

- Limit 20 user characteristics. Each description up to 20 characters.
- Services are identified only by UUID when constructing characteristics. No separate service class.
- `BleCharacteristic`:
  - No-arg constructor for central-role use. Attach `onDataReceived` after connecting.
  - Peripheral constructor: description, properties, characteristic UUID, service UUID. Register with `BLE.addCharacteristic()`.
  - Peripheral with data-received callback and context.
  - `UUID()`, `properties()`.
  - `getValue()` and `setValue()`: overloads for raw buffers, strings, and typed values.
  - `onDataReceived()` callback signature `(data, len, peer, context)`. Runs on the BLE thread. Set flags and do heavy work in `loop()`.
- `BleCharacteristicProperty` bitfield: BROADCAST, READ, WRITE_WO_RSP, WRITE, NOTIFY, INDICATE, AUTH_SIGN_WRITES (unsupported), EXTENDED_PROP (unsupported). Peripherals typically use NOTIFY (outgoing) or WRITE_WO_RSP (incoming).
- `BleUuid`: constructors from 16-bit, string, 128-bit byte array. `type()` returns SHORT or LONG. `valid()` (3.0.0+). Equality operators. `rawBytes()`.

### Scanning (central role)

- `BLE.scan(array)`: synchronous. Default timeout 5 s. OS 3.0+ accesses `BleScanResult` fields as methods. OS 3.1.0 may return error -270; the docs give a `BLE.setScanPhy()` workaround.
- `BLE.scan(Vector)`: dynamically allocated results.
- `BLE.scan(callback, context)`: callback as devices are found. Returns after the timeout. Cannot call `BLE.connect()` from the callback.
- `BLE.scanWithFilter(BleScanFilter)` (3.0.0+): returns matches via callback, array, or `Vector<BleScanResult>`.
- `BLE.stopScanning()`: ends a scan early, typically from the callback.
- `BLE.setScanTimeout(uint16_t)`: units 10 ms, default 500 (5 s).
- `BLE.getScanParameters(BleScanParams*)` / `setScanParameters(const BleScanParams*)`.
- `BLE.setScanPhy(EnumFlags<BlePhy>)` (3.1.0+): Coded PHY (long range). Not on P2 or Photon 2. Do not combine `BLE_PHYS_AUTO` with other values. Device OS 3.0.0 has a bug that needs an explicit `BLE_PHYS_AUTO` in `setup()`.
- Callbacks run on the BLE thread with a small stack. Avoid `Particle.publish()`, `delay()`, and logging there. Scanning and advertising together is discouraged.

### BLE scan filter (3.0.0+)

Filters combine with AND: `deviceName`, `serviceUUID`, `address`, `appearance`, `rssi` (`minRssi`/`maxRssi`), `customData`. Each has single-item and vector setters.

### Connecting (central role)

- `BLE.connect(addr, [params], automatic)`: synchronous. Returns a `BlePeerDevice`. Check `connected()`. Addresses can change, so be ready to rescan.
- `BLE.connect(options)`: interval (1.25 ms units, default 24), latency (use 0), timeout (10 ms units, default 500, minimum 100). Timeout applies after connection.
- `BLE.setPPCP()`: default connection parameters for `connect()` calls that omit options.
- Connection limits:
  - Gen 4 (P2, Photon 2, M-SoM): 4 open links.
  - Gen 3 (nRF52): 3 central connections, or 1 in Device OS 1.3.0.
  - A device cannot be central and peripheral at once.
- `BLE.connected()`: true if connected in either role.
- `BLE.disconnect()` and `BLE.disconnect(peripheral)`: return 0 on success. Cannot be called from a BLE callback.
- `BlePeerDevice`: `connected()`, `address()`, `getCharacteristicByUUID()`, `getCharacteristicByDescription()`, `discoverAllCharacteristics()` (3.0.0+).

### Pairing (3.0.0+)

- `setPairingIoCaps()`, `setPairingAlgorithm()`, `startPairing()`, `rejectPairing()`, `setPairingNumericComparison()`, `setPairingPasskey()`, `isPairing()`, `isPaired()`, `onPairingEvent()`.
- LESC support varies: 3.1.0 for nRF52840, 5.1.0 for RTL872x.
- Structures: `BlePairingEvent`, `BlePairingEventPayload` (passkey or status), `BlePairingStatus`.

### Provisioning (3.3.0+)

- `setProvisioningSvcUuid()`, `setProvisioningTxUuid()`, `setProvisioningRxUuid()`, `setProvisioningVerUuid()`. Must be called before BLE setup starts.
- `BLE.setDeviceName()` / `getDeviceName()`: limit `BLE_MAX_DEV_NAME_LEN` (20). 14 or fewer characters fit the advertising packet. With provisioning UUIDs, the name is limited to 8 bytes.
- `BLE.setProvisioningCompanyId()`: default 0x0662.
- `BLE.provisioningMode(bool)` and `getProvisioningStatus()`. Provisioning advertising replaces custom advertising while active.

## Ethernet

Hardware-dependent. Ethernet is not on the Photon 2 board itself. It requires an external module (Particle Ethernet, Adafruit Ethernet, B-SoM eval board, M.2 breakout, Muon, Tracker SoM) with pin remapping.

### Pin reference

| Board | CS | RESET | INT |
|---|---|---|---|
| Particle Ethernet | D5 | D3 | D4 |
| Adafruit Ethernet | D5 | not connected by default | not connected by default |
| B-SoM eval and M.2 breakout | D8 | A7 | D22 |
| Muon | A3 | not connected | A4 |
| Tracker SoM | D2 | D6 | D7 |

- Device OS 5.9.0+ can run without RESET and INT. The CS pin is always required. Without INT, the driver polls, which reduces performance.

### Remap procedure

Since 5.3.0. Fill an `if_wiznet_pin_remap` struct (`base.type = IF_WIZNET_DRIVER_SPECIFIC_PIN_REMAP`, plus `cs_pin`, `reset_pin`, `int_pin`), then call `if_request(nullptr, IF_REQ_DRIVER_SPECIFIC, &remap, sizeof(remap), nullptr)`. Success returns `SYSTEM_ERROR_NONE`.

Required order:
1. Keep `FEATURE_ETHERNET_DETECTION` disabled until remapping is complete, so default GPIO is not probed.
2. Use threading and `SYSTEM_MODE(SEMI_AUTOMATIC)`. Threading defaults to on in 6.2.0+.
3. If `Ethernet.isOn()` is false, apply the remap.
4. Enable `FEATURE_ETHERNET_DETECTION` with `System.enableFeature()`, then call `System.reset()`.

Persistence: the remap survives reset, cold boot, application flashing, and Device OS upgrade. Safe mode also uses it, so OTA upgrades over Ethernet still work.

Reset to defaults: as of 6.1.1, `PIN_INVALID` means "no interrupt pin," not "restore defaults." Restore defaults by passing `HAL_PLATFORM_ETHERNET_WIZNETIF_CS_PIN_DEFAULT`, `..._RESET_PIN_DEFAULT`, `..._INT_PIN_DEFAULT`.

Muon and M.2 breakout run `auxiliaryPowerControlPin` and `interruptPin` first. `setup.particle.io` automates the Muon setup.

### Ethernet class

- `on()`, `off()`, `isOn()` (2.1.0+), `isOff()` (2.1.0+).
- `connect(unsigned flags = 0)`: may return before an IP is assigned. Check `ready()`.
- `disconnect()`: leaves the module on.
- `connecting()`.
- `ready()`: true when link is up, IP assigned, DNS configured, and gateway set. Isolated LANs (gateway 0.0.0.0) never report ready. Use `!Ethernet.connecting() && Ethernet.localIP() != IPAddress()` instead.
- `setConfig(const NetworkInterfaceConfig&)` and `getConfig(profile)` (5.3.0+).
- `prefer(bool)` (5.7.0+): preference only matters when multiple interfaces are available. Takes effect on the next connection management cycle, usually after cloud disconnect. Preferring Ethernet clears Cellular or Wi-Fi preference.
- `isPreferred()`: reports the setting only, not the interface in use.
- `ping()` (6.3.0+): ICMP ping, not the cloud ping. Default timeout 4000 ms. Unknown hostname returns `SYSTEM_ERROR_NOT_FOUND` (-150).
- `listen()`, `listening()`, `setListenTimeout()`, `getListenTimeout()`.
- `macAddress(uint8_t*)`, `localIP()`, `subnetMask()`, `gatewayIP()`, `dnsServerIP()`, `dhcpServerIP()`. Some DNS and DHCP values often return 0.0.0.0.

## NetworkInterfaceConfig (5.3.0+)

- `source()`: `NetworkInterfaceConfigSource::DHCP` (default) or `::STATIC`. Persistent.
- `address()`: takes `NetworkInterfaceAddress`, `SockAddr` pair, or `IPAddress` address and mask.
- `gateway()`: set `{0,0,0,0}` to stop Ethernet being the default route, including for cloud access. Use for isolated LANs. Local TCP and UDP still work.
- `dns()`: call multiple times to add servers.

## Network class (generic)

Works with Cellular, Wi-Fi, or Ethernet. Use it to avoid `#ifdef` checks.

- `on()`, `off()`, `connect()`, `disconnect()`, `connecting()`, `ready()`. Apply to the default interface. `off()` requires `Particle.disconnect()` first.
- `setConfig()`, `getConfig()` (5.3.0+).
- `prefer()` (5.7.0+): clears all specific-interface preferences.
- `isPreferred()` (5.6.0+): true when automatic connection management is in use.
- `ping()` (6.3.0+): on cellular, consumes data.
- `listen()` family.

## Tether (6.2.0+)

Lets another device use this device's cellular connection over PPP.

- `TetherSerialConfig`:
  - `serial()`: a hardware serial port (not USB). Hardware flow control recommended.
  - `config()`: default `SERIAL_8N1 | SERIAL_FLOW_CONTROL_RTS_CTS`.
  - `baudrate()`: default 921600.
- `on()` enables tethering (default off). `connect()` starts the PPP server, typically after cellular connects. `off()` disables. `disconnect()` stops the connection but leaves it enabled.
- `connecting()` is true while the PPP server starts. `ready()` is true once it accepts requests.
- `localIP()`, `subnetMask()`, `gatewayIP()` return the PPP server's addresses.

## TCPServer, TCPClient, UDP

- Not supported on cellular devices.
- The docs recommend `Particle.publish()` and webhooks over direct TCP. Sleep mode drops TCP connections, and cellular data cost matters.

### TCPServer

- Constructor takes a port and an optional interface (6.2.0+ also allows `Tether`).
- `begin()`, `available()`, `write()` (with optional timeout), `print()`, `println()`, `getWriteError()`, `clearWriteError()`.

### TCPClient

- `connect()` by IP or hostname, optional interface.
- `connected()`, `status()`, `write()`, `print()`, `println()`, `available()`, `read()`, `flush()` (currently does nothing), `remoteIP()`, `stop()`, `getWriteError()`, `clearWriteError()`.

### UDP

- `begin()`, `available()`, `beginPacket()`, `endPacket()`, `write()`, `parsePacket()`, `receivePacket()`, `read()`, `flush()` (currently does nothing), `stop()`, `remoteIP()`, `remotePort()`.
- `setBuffer()` (default 512 bytes), `releaseBuffer()`, `sendPacket()`, `joinMulticast()`, `leaveMulticast()`.
- Delivery not guaranteed. Gen 4 devices may need `begin()` again after reconnecting.

## SoftAP HTTP pages (Photon and P1 only)

- Not available on cellular, Argon, P2, or Photon 2.
- Registered with `STARTUP(softap_set_application_page_handler(myPages, nullptr));`
- Handler: `void myPages(const char* url, ResponseCallback* cb, void* cbArg, Reader* body, Writer* result, void* reserved);`
- The application must always call `cb` to respond. `flags` must be 0.
- Request body: `body->bytes_left` and `body->fetch_as_string()`. Caller must `free()` the returned string.
- `/` redirects to `/index`. Use status 301 with a `Location` header to redirect.

## Cross-references

- Cloud connect and keep-alive: [07-cloud-connection-and-system-modes.md](07-cloud-connection-and-system-modes.md).
- Power draw for Wi-Fi and BLE: [02-power-and-sleep.md](02-power-and-sleep.md).
- Antenna and RF specs: [01-hardware-datasheet.md](01-hardware-datasheet.md).
