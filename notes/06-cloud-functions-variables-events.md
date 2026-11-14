# Cloud Functions, Variables, Publish, and Subscribe

Source: Device OS firmware reference (Particle.function, Particle.variable, Particle.publish, Particle.subscribe, field size limits). Retrieved 2026-11-13. Verify version-specific limits on the live page.

Access model for all three: these are reached through the Particle Cloud API or tools built on it (console, CLI, mobile app). A device cannot call or read another device directly, even on the same account. Use publish/subscribe for device-to-device communication.

## Particle.function()

Exposes a callable function that the cloud can invoke.

### Signatures

```cpp
bool function(const char *funcKey, user_function_int_str_t *func);
bool function(const char *funcKey, user_std_function_int_str_t func);
template <typename T>
bool function(const char *funcKey, int (T::*func)(String), T *instance);

typedef int (user_function_int_str_t)(String paramString);
```

- Callback must return `int` and take exactly one `String` argument.
- Return `-1` is the docs' common failure signal.
- Registration returns `bool` (success).

### Limits

- Up to 15 registered functions.
- Name length: 64 characters since 0.8.0 (12 before).
- One `String` argument per call. Argument count cannot vary.
- Argument size: see the field size table below.
- Name characters: letters, numbers, underscores, dashes. Avoid spaces and special characters, since tools may escape them unexpectedly.

### Timing and execution

- The callback must return quickly. Otherwise the cloud call times out. The timeout duration is not stated in the docs.
- Callbacks run in the application loop thread context, between `loop()` calls, during `Particle.process()`, and during `delay()`.
- Each request and response consumes one Data Operation. Registration does not.

### Registration timing

- AUTOMATIC mode (default): register in `setup()`. The cloud learns about it after `setup()` finishes.
- SEMI_AUTOMATIC and MANUAL: register before `Particle.connect()`.
- Before 1.5.0: registrations were sent once, about 30 seconds after connecting. Register early in `setup()`.
- Calling `Particle.function()` after registration has been sent does not resend it. The function will not work.
- Do not call `Particle.function()` from the constructor of a global object. Call it from `setup()`.

### Access

- Only the claiming account can call a function. For product devices, the device owner's account can call if the device is claimed, and the product owner can call whether or not it is claimed.

### C++ member function

```cpp
class CoffeeMaker {
  public:
    void setup() {
      Particle.function("brew", &CoffeeMaker::brew, this);
    }
    int brew(String command) { return 1; }
};
```

### Example

```cpp
int brewCoffee(String command);

void setup() {
  Particle.function("brew", brewCoffee);
}

int brewCoffee(String command) {
  if (command == "coffee") {
    return 1;
  }
  return -1;
}
```

Calling it from the cloud:

```bash
curl https://api.particle.io/v1/devices/0123456789abcdef/brew \
     -H "Authorization: Bearer <ACCESS_TOKEN>" \
     -d "arg=coffee"
```

The response includes a `return_value` key with the integer returned.

Get a token with `particle token create` (see [11-particle-cli.md](11-particle-cli.md)).

## Particle.variable()

Exposes a readable value the cloud can fetch.

### Signatures

```cpp
bool variable(const char *varKey, const bool &var);
bool variable(const char *varKey, const int &var);
bool variable(const char *varKey, const double &var);
bool variable(const char *varKey, const String &var);
bool variable(const char *varKey, const char *var);

// Calculated (1.5.0+): called only when the cloud requests the value
bool variable(const char *varKey, std::function<bool()> fn);
bool variable(const char *varKey, std::function<int()> fn);
bool variable(const char *varKey, std::function<double()> fn);
bool variable(const char *varKey, std::function<String()> fn);
```

### Rules

- Supported types: `bool`, `int`, `double`, `String`, and `char*` (UTF-8 text). Before 0.4.7, the type and `&` address were passed explicitly.
- Name length: 64 characters since 0.8.0 (12 before).
- Up to 20 variables can be registered.
- Storage must be global, `static`, a class member on a non-stack object, or heap-allocated. Stack locals are not valid.
- Value size: depends on Device OS version (see table). Since 6.3.0, 1024 bytes.
- Name characters: letters, numbers, underscores, dashes.
- Registration timing: same as functions.
- Each cloud read costs one Data Operation. Setting the value locally costs nothing.
- Only the claiming account (or product owner) can read values.
- Calculated variables run in the same context as function callbacks (loop thread, between `loop()` calls, during `Particle.process()` and `delay()`). Class methods can be passed as lambdas that capture `this`.

## Particle.publish()

Sends an event from the device to the cloud. Events go to webhooks, the console, other devices via subscribe, and integrations.

### Signatures

```cpp
// 6.3.0+: recommended, asynchronous, no Future returned
bool publish(particle::CloudEvent event);

// 6.2.0+
particle::Future<bool> publish(const char* name, const char* data, particle::ContentType type, PublishFlags flags = PublishFlags());
particle::Future<bool> publish(const char* name, const String& data, particle::ContentType type, PublishFlags flags = PublishFlags());
particle::Future<bool> publish(const char* name, const char* data, size_t size, particle::ContentType type, PublishFlags flags = PublishFlags());
particle::Future<bool> publish(const char* name, const particle::EventData& data, PublishFlags flags = PublishFlags());

// Classic
particle::Future<bool> publish(const char* name);
particle::Future<bool> publish(const char* name, const char* data);
particle::Future<bool> publish(const char* name, PublishFlags flags1, PublishFlags flags2 = PublishFlags());
particle::Future<bool> publish(const char* name, const char* data, PublishFlags flags1, PublishFlags flags2 = PublishFlags());
```

### Event name

- 1 to 64 ASCII characters. Letters, numbers, underscores, dashes, and slashes.
- Names beginning with "particle" or "spark" (case-insensitive) are reserved.

### Content types (6.2.0+)

| Constant | MIME type | Value |
|---|---|---|
| `TEXT` | text/plain; charset=utf-8 | 0 |
| `JPEG` | image/jpeg | 22 |
| `PNG` | image/png | 23 |
| `BINARY` | application/octet-stream | 42 |
| `STRUCTURED` | structured (CBOR/JSON) | 65001 |

### Publish flags

- `WITH_ACK`: blocks until the cloud acknowledges.
- `NO_ACK`: sends once, no retry, reduces data use.
- Flags combine with `|`.
- `PRIVATE` is the only scope and is always used. `PUBLIC` is no longer supported.
- Without `WITH_ACK`, the device retransmits internally up to 3 times.

### Data size limits (see also field size table)

- 6.3.0+ on Gen 3 and Gen 4: 16384 bytes, but only through CloudEvent. Binary allowed.
- 6.2.0+ on Gen 3 and Gen 4: 1024 bytes. Binary allowed.
- 3.x to 6.1.x on Gen 3 and Gen 4: 1024 UTF-8 characters. No binary.
- Older versions and Gen 2: 864, 622, or 255 UTF-8 characters.

### Rate limits

- Device OS 6.2.x and earlier: about 1 event per second, with bursts up to 4 per second. A burst of 4 takes about 4 seconds to recover.
- Device OS 6.3.0+: the docs defer to the typed-publish page, which was not captured. See [12-gaps-and-unverified.md](12-gaps-and-unverified.md).

### Behavior

- Each publish costs one Data Operation, with or without ACK.
- If the cloud connection is off, `publish()` returns `false`.
- If connection attempts are failing, `publish()` can block for about 20 seconds normally, or up to 10 minutes in unusual cases. Check `Particle.connected()` first.
- Deprecated TTL overloads (`publish(name, data, int ttl, flags)`) remain for compatibility. The cloud has never honored TTL.
- Delivery is not end-to-end confirmed. Events can be duplicated, arrive out of order, or be delivered even when `publish()` returned `false`.
- `Particle.publish()` and subscribe handlers share one buffer. Publishing inside a handler corrupts the incoming data unless you copy it first.
- Classic publish cannot send raw binary. Encode as Base64 or hex. The docs advise against Base85 for webhook payloads.

## Particle.subscribe()

Receives events published by other devices or by the cloud.

### Signatures

```cpp
// Classic
bool subscribe(const char* name, EventHandler handler);
bool subscribe(const char* name, wiring_event_handler_t handler);
template<typename T>
bool subscribe(const char* name, void (T::*handler)(const char*, const char*), T* instance);
typedef void (*EventHandler)(const char *event_name, const char *data);

// 6.2.0+: content type and size passed to handler
bool subscribe(const char* name, particle::EventHandlerWithContentType handler);
bool subscribe(const char* name, particle::EventHandlerWithContentTypeFn handler);
// handler: void(const char* name, const char* data, size_t size, ContentType type)

// 6.2.0+: structured data as Variant
bool subscribe(const char* name, particle::EventHandlerWithVariant handler);
bool subscribe(const char* name, particle::EventHandlerWithVariantFn handler);
// handler: void(const char* name, EventData data)

// 6.3.0+: CloudEvent
bool subscribe(const char* name, particle::EventHandlerWithCloudEvent* handler,
        const particle::SubscribeOptions& opts = particle::SubscribeOptions());
bool subscribe(const char* name, std::function<particle::EventHandlerWithCloudEvent> handler,
        const particle::SubscribeOptions& opts = particle::SubscribeOptions());
// handler: void(CloudEvent event)
```

### Rules

- Matching is by prefix. Subscribing to `foo` matches `foo`, `fool`, and `food/indian/sweet-curry-beans`. Max prefix length 64 characters.
- Up to 4 handlers per device (higher on some versions and devices). Later calls return `false`.
- Subscriptions can be made in `setup()` or `loop()` and take effect once `loop()` is running. Registrations made while offline are sent on next connect.
- Each delivery costs one Data Operation, up to 3 attempts on poor connectivity. Offline devices incur none.
- `SubscribeOptions::structured(bool)` (6.3.0+): compact structured encoding. Default `false`.
- `Particle.unsubscribe()` removes all handlers. There is no per-handler removal.
- `MY_DEVICES` and `ALL_DEVICES` are no longer needed. `ALL_DEVICES` stopped working in August 2020.
- Since March 2023, unclaimed product devices can receive subscribed events.
- Delivery not guaranteed; can duplicate or reorder.
- Webhook responses: include the device ID in the topic, e.g. `System.deviceID() + "/hook-response/weather/"`, so responses meant for other devices do not consume your Data Operations.

## Field size limits by Device OS version

| Field | Before 0.8.0 | 0.8.0 to 2.x | 3.0.0+ | 6.3.0+ |
|---|---|---|---|---|
| Variable key | 12 | 64 | 64 | 64 |
| Variable data | 622 (see note) | 622 | 864 (Gen 2) / 1024 (Gen 3+) | 1024 |
| Function key | 12 | 64 | 64 | 64 |
| Function argument | 63 | 622 | 864 (Gen 2) / 1024 (Gen 3+) | 1024 |
| Event name | 64 | 64 | 64 | 64 |
| Event data | 255 | 622 | 864 (Gen 2) / 1024 (Gen 3+) | 16384 (CloudEvent only) |

Notes:
- Limits are bytes of UTF-8 text, except in 6.2.0 and later, where data can be binary.
- The 0.8.0 to 2.x column is frozen. Higher limits are not back-ported.
- The "before 0.8.0" variable-data cell reads "622" in the source, which looks like a footnote marker. Confirm against the live page.
- Some older Boron and B-Series SoM units with SARA-R410M-02B modem firmware 02.03 or earlier are limited to 782 bytes.
- Use constants rather than hardcoding: `particle::protocol::MAX_VARIABLE_KEY_LENGTH`, `MAX_VARIABLE_VALUE_LENGTH`, `MAX_FUNCTION_KEY_LENGTH`, `MAX_FUNCTION_ARG_LENGTH`, `MAX_EVENT_NAME_LENGTH`, `MAX_EVENT_DATA_LENGTH`.
- Runtime queries (3.1.0+): `Particle.maxEventDataSize()`, `Particle.maxVariableValueSize()`, `Particle.maxFunctionArgumentSize()`. These return `SYSTEM_ERROR_INVALID_STATE` (-210) when not connected.

## Quick reference for design

- Cloud calls a device: `Particle.function`. Read a value: `Particle.variable`. Device pushes to cloud: `Particle.publish`. Device reacts to another device's event: `Particle.subscribe`.
- Each cloud call and each event delivery costs Data Operations. Plan rates accordingly.
- Use `NO_ACK` for high-frequency, loss-tolerant telemetry. Use `WITH_ACK` when delivery to the cloud matters, and accept the blocking cost.
