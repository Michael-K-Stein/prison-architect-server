# Journal 2

## Parsing `RaiseEvent` payloads (Claude Opus 5.5 work)

> **This section was written by Claude Opus 5.5** (an AI assistant), from its
> analysis of `captures/run1.sqlite`. It was not verified by hand.

### The capture

`captures/run1.sqlite`: set up an "online" game, then let time run for a few
seconds. Ignore the Name Server and Master Server sessions (1 and 2). Session 3
(the Game Server) has 74 client -> server `Operation: RaiseEvent`. There are no
server -> client game events, because only one client was connected.

Every `RaiseEvent` has two params:

- **Code (244)**, `Int8Parameter`: the game's own event type.
- **Data (245)**, `Int8SliceParameter`: the payload, described below.

### Data: a list of tagged values

| Tag    | Meaning                                                               |
| ------ | --------------------------------------------------------------------- |
| `0x0N` | a whole number in N-1 little-endian bytes (`0x00` = 0)                 |
| `0x1N` | a byte string, length in N-1 little-endian bytes (`0x12` 1B, `0x13` 2B) |

### Event codes seen

- **9** (73 of 74): one simulation system's state, `[system name, snapshot]`.
  "SystemState" is our name for it, not the game's. Systems seen:
  `PlayerData`, `ObjectData`, `ConstructionSystem`, `Finance`, `Intake`,
  `NeedsDistribution`, `NetworkSoundSystem`, `World`. After the first sends,
  the client loops through `ObjectData`, `ConstructionSystem`, `Intake` and
  `World`.
- **118** (once, at game start): `[35, "finance_cost_cashflow", 0, 0]`. We
  don't know what it means yet.

### The snapshot (event 9)

- The snapshot is zlib-compressed (starts with `78 9c`).
- After the zlib stream comes the uncompressed size, written backwards: the
  size bytes in big-endian order, then a byte giving their count + 1.
  Example: `01 dc 03` = 476 bytes. The parser checks this on every packet.
- Uncompressed, the snapshot is a binary version of the save-file tree. Each
  block is laid out as:

  ```
  '<'  name(u8 len + bytes)
       field count (u8), then each field: name, type (u8), value
       child count (u8), then the child blocks
  '>'
  ```

- Field types:

  | Type | Value                                                              |
  | ---- | ------------------------------------------------------------------ |
  | `01` | int32                                                              |
  | `02` | float32                                                            |
  | `04` | string (u8 length)                                                 |
  | `05` | bool (1 byte)                                                      |
  | `06` | u32 length, then a nested tagged list, e.g. `[0, '_Finance', 'ReceivePaymentSmall', 0]` |
  | `07` | double, e.g. `TimeIndex`                                           |
  | `08` | u16                                                                |

Example:

```
Event 9 (SystemState):
  'World'
  snapshot: 619 B zlib -> 3015 B
    World
      WorldData {TimeIndex=607.562, SecondsPlayed=61, Balance=30110}
      RoadDeliveryData
      CrisisSectorData
        0 0 {value=False}
        ...
```

### Code

- **`pa_events.py`**:
  - `decode_args` reads the tagged list.
  - `decompress` and `decode_tree` read the snapshot.
  - `log_lines(packet)` returns `packet.log()` with the raw Data line
    replaced by the parsed one.
- **`main.py`**: the proxy debug view (`show`) uses `log_lines`. If a payload
  doesn't parse, it's shown as raw hex with the reason.
- **`tests/test_pa_events.py`**: tests on real bytes from the capture. Added to
  CI.

All 74 `RaiseEvent`s in the capture parse.

### Open questions

- `ObjectData`'s `p` and `v` fields (int32) look like two 16-bit values packed
  together, probably fixed-point at 1/256: a position and a velocity? For
  example, `p = 0x55815136` gives (81.2, 85.5).
- Names and counts are read as single bytes. That holds here (the largest is
  154 children), but a big prison might go over 255.
- What does event 118 mean? What are the other event codes?
- Server -> client events have not been seen yet. Their parsing (the event
  code is in the event header, Data is in param 245) is untested.
