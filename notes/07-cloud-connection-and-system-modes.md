# Cloud Connection, System Modes, Threading, Time Sync

Source: Device OS firmware reference (Particle.connect, disconnect, connected, keepAlive, process, syncTime, SYSTEM_THREAD). The "System" class (`System.reset`, `System.sleep`, `System.enableUpdates`, `System.factoryReset`, `System.version`, etc.) was NOT captured. The truncated pages did not reach it. See [12-gaps-and-unverified.md](12-gaps-and-unverified.md).

## System modes

- Default: `SYSTEM_MODE(AUTOMATIC)`. The device connects to the cloud on its own. Variables and functions must be registered in `setup()`. The cloud learns about them after `setup()` finishes.
- `SYSTEM_MODE(SEMI_AUTOMATIC)`: you call `Particle.connect()`. Register functions and variables before connecting.
- `SYSTEM_MODE(MANUAL)`: you manage the connection and the network. Call `Particle.process()` often, ideally every `loop()` pass and inside any blocking code. Register before connecting.
- Use `WiFi.off()` and `Cellular.off()` (or `Network.off()`) only in SEMI_AUTOMATIC or MANUAL mode.

The firmware reference's system-mode section itself was not captured, so details beyond the above are not in these notes.

## SYSTEM_THREAD

- `SYSTEM_THREAD(ENABLED)` is recommended for most applications. This runs the system (cloud, network) on its own thread.
- Threading defaults to on in Device OS 6.2.0+. Guard for older releases:

```cpp
#ifndef SYSTEM_VERSION_v620
SYSTEM_THREAD(ENABLED);
#endif
```

- With threading, `delay()` and blocking calls in `loop()` do not stop the cloud connection.
- `listening()` returns false without threading. Listening mode blocks application code unless threading is used.
- Without threading in AUTOMATIC mode, `BLE.connect` and `timeSyncedLast()` and similar may block. Prefer threading.

## Particle.connect()

```cpp
static void connect(void);
```

- Connects to the cloud and activates the network if needed.
- Device OS normally calls this at boot. Call it yourself only in SEMI_AUTOMATIC or MANUAL mode.
- Gen 3 before 2.0.0 required `WiFi.on()` or `Cellular.on()` first. Not needed on Gen 2 or on 2.0.0+.
- Connecting itself uses no Data Operations, but cellular devices consume cellular data.
- Cellular retry guidance from the docs:
  - Use a timeout of at least 120 seconds. Connection can take much longer on 3G and 2G.
  - Stay awake trying to connect for at least 5 minutes periodically so the SIM can cycle IMSIs.
  - After 10 minutes of failure, Device OS fully shuts down and restarts the modem. Wait at least 11 minutes.
  - For battery savings, use a backoff that still retries at least every few hours.

## Particle.disconnect()

```cpp
static void disconnect(const CloudDisconnectOptions& options = CloudDisconnectOptions());
```

- Disconnects from the cloud but keeps the network up. Use `WiFi.off()` or `Cellular.off()` to deactivate the network module.
- Asynchronous. Wait with `waitUntil(Particle.disconnected)`.
- Default is abrupt. Since 2.0.0, `graceful(true)` and `timeout()` let pending events finish sending:

```cpp
Particle.disconnect(CloudDisconnectOptions().graceful(true).timeout(5s));
```

- While disconnected: no OTA updates, no variable reads, no function calls. Over-the-air flashing is not possible. Safe mode can reconnect.
- Since 5.6.0, automatic connection management takes over on the next connection. Avoid manual disconnects in normal use, since they cost cellular data.
- To discard the session: `CloudDisconnectOptions().clearSession(true)`, rather than the older `spark/device/session/end` approach.
- `setDisconnectOptions(const CloudDisconnectOptions&)` (2.0.0+) sets graceful behavior globally, so `System.reset()` and similar calls also disconnect gracefully.

## State checks

- `Particle.connected()`: true when connected to the cloud. Fast and safe to call often.
- `Particle.disconnected()`: true when disconnected.
- `Particle.connectionInterface()` (5.6.0+): the interface carrying the cloud connection.

## Particle.keepAlive()

Sets the interval between keep-alive pings that keep the cloud-to-device path open.

```cpp
static void keepAlive(unsigned sec);                                // all Gen 3 and Gen 2 cellular
static void keepAlive(unsigned sec, network_interface_t network);   // 6.5.0+
static void keepAlive(std::chrono::seconds s, network_interface_t network); // 6.5.0+
static int getKeepAlive();                                          // 6.5.0+
static int getKeepAlive(network_interface_t network);               // 6.5.0+
```

- Example: `Particle.keepAlive(23 * 60);` or `Particle.keepAlive(2min);` (chrono since 1.5.0).
- Each ping uses 122 bytes of data (61 sent, 61 received). Very short intervals raise cellular data use.
- Keep-alives do not use Data Operations.
- If a function call or variable get times out, too-infrequent keep-alive is one possible cause.

Defaults:

| Device | Default keep-alive |
|---|---|
| All cellular | 23 minutes |
| Argon (below 3.0.0) | 30 seconds |
| Argon (3.0.0+) | 25 seconds |

Precedence (6.5.0+), highest first:
1. Runtime value set with `Particle.keepAlive(sec, network)`.
2. Interface-specific environment variable: `PARTICLE_CELLULAR_CLOUD_KEEP_ALIVE`, `PARTICLE_WIFI_CLOUD_KEEP_ALIVE`, or `PARTICLE_ETHERNET_CLOUD_KEEP_ALIVE`.
3. Global environment variable `PARTICLE_CLOUD_KEEP_ALIVE`.
4. Device OS default from the table.

A runtime value takes effect on the next cloud connection on that interface, not immediately. Environment variable changes also apply on the next (re)connection.

## Particle.process()

- With `SYSTEM_THREAD(ENABLED)`, you generally do not need it. From 6.2.0, the system thread is always enabled.
- In AUTOMATIC or SEMI_AUTOMATIC, you usually do not need it unless `loop()` blocks. Inside a blocking inner loop, call `delay()` or `Particle.process()`.
- In MANUAL, call it frequently.
- It receives cloud messages, sends keep-alives, and calls `ApplicationWatchdog::checkin()`. If it is not called often enough, the cloud connection can be lost.

## Time sync

```cpp
bool syncTime(void);
bool syncTimeDone(void);
bool syncTimePending(void);
system_tick_t timeSyncedLast(void);
system_tick_t timeSyncedLast(time_t& tm);
```

- Device time syncs automatically on connect. Call `syncTime()` manually on long-running devices, for example once a day.
- `syncTime()` only sends the request. The time updates later, between `loop()` calls, when the cloud responds.
- `syncTimeDone()` returns false while a request is pending. Use `waitUntil(Particle.syncTimeDone)`.
- `syncTimePending()` returns true while pending.
- `timeSyncedLast()` returns ms since program start at the last sync. The overload also returns the UNIX timestamp.
- `timeSyncedLast()` can block up to about 10 minutes if the system thread is stuck reconnecting to cellular. Call it from a worker thread to avoid this.
- Time sync uses no Data Operations. It does use cellular data on cellular devices.

Time formatting and zones: see [08-time-timers-watchdogs-leds.md](08-time-timers-watchdogs-leds.md).

## Related

- Cloud function, variable, publish, and subscribe: [06-cloud-functions-variables-events.md](06-cloud-functions-variables-events.md).
- Keep-alive and connect costs on cellular: [05-wifi-ble-network.md](05-wifi-ble-network.md) and [02-power-and-sleep.md](02-power-and-sleep.md).
