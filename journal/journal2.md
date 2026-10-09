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

## `captures/run2.sqlite`: `SetProperties` and event 118 (Claude Sonnet 5.5 work)

> **Written by Claude Sonnet 5.5** from `captures/run2.sqlite`. Not verified by
> hand; items marked *guess* are inference, not observation.

### The capture

Two "online game" runs of the same game process: sessions 3 (Game Server, ~8 s)
and 7 (Game Server, ~35 s). Sessions 1/2/5/6 are Name/Master, 4 is a short
reconnect. Photon operation 252 = `SetProperties`, 253 = `RaiseEvent`.

### `SetProperties` (operation 252)

Always client -> server, always `ActorNr = 1`, `Broadcast = True`, and a
one-entry hashtable `Properties(251)`. The server answers with an empty
`OperationResponse` (6 B). Two keys occur:

| Key | Type | Seen | Meaning |
| --- | ---- | ---- | ------- |
| `C` | string `"0x8479f4ff"`, `"0xbb9197ff"` | once per session, right after joining (before the first game event) | The player's colour, as `0xRRGGBBAA` (alpha always `ff`). Differs per session. Confirmed by the user: each player has a colour in the game's UI. |
| `P` | int32 `326`..`335` | every ~4.0 s in session 7 (6.0, 10.1, 14.1, 18.1, 22.1, 26.1, 30.2 s) | The player's ping in ms. Matches the measured request -> response gap in the capture (~318-320 ms) closely. Values seen: 335, 328, 329, 331, 329, 332, 333, 335, 326. Confirmed by the user: `P` sets the actor's ping. |

Nothing else is sent through `SetProperties`; the game's own state goes through
`RaiseEvent`. Session 3 only sends `P` once (122) because it lasts 8 s.
So `SetProperties` is Photon's *actor custom properties* (a per-player
key/value bag): colour and ping, used by the lobby/player list.

### `RaiseEvent` 118 (`finance_cost_cashflow`)

Payload: `[35, "finance_cost_cashflow", 0, 0]` (`02 23 | 12 15 <21 bytes> | 00 | 00`).
Seen 3 times in run2 (packet 31 in session 3, 265 and 732 in session 7) and
once in run1. Always identical.

What it does, from the `Finance` and `World` snapshots right after it:

| Packet | Event 118 | `Finance` snapshot after it | `World.Balance` |
| ------ | --------- | --------------------------- | ---------------- |
| run1 s3, 31 | `35` | `tr.b=30075, v.6=30110` | 30110 |
| run2 s3, 31 | `35` | `tr.b=30110, v.6=30145` | 30145 |
| run2 s7, 265 | `35` | `tr.b=30145, v.6=30180` | 30180 |
| run2 s7, 732 (t=22.3 s) | `35` | `tr.b=30180, v.6=30215` | (not re-sent) |

Every time, `v.6 = tr.b + 35` and `World.Balance` becomes `v.6`. The balance
is cumulative over the runs (one game process, balance carried over), so each
118 added exactly 35 to the bank balance, and the balance is the same
afterwards for host and `World`.

Reading:

- **Arg 0 (`35`) is the amount** of a one-off cash-flow item. Both its constancy
  and the exact +35 on the balance fit. Whether it is a literal $35 or a
  value derived from game state (e.g. one game-day's running cost) is not
  distinguishable here, since it was 35 in all four samples.
- **Arg 1 is the ledger category/key**: `finance_cost_cashflow`, a finance
  cost-category name (the game's `Finance` system has `tr.b`, `v.6`... style
  keys; `tr` is probably "transactions", `b` "balance"). The "cost" in the name
  is odd since the balance *rose*; maybe the event just means "apply this
  cash-flow entry" and the sign is in the game's bookkeeping. *guess*
- **Args 2, 3 (`0`, `0`)**: unused here. Possibly a sub-type and a flag/
  position (other finance events might use them). Unknown.
- **When**: right after `CreateGame`/`SetProperties(C)`, before the first
  `SystemState` burst (packet 31 comes 0 ms before `PlayerData`, `ObjectData`...,
  `Finance`). The third one (732) was sent alone mid-session, 22 s in, between
  two `World`/`Intake` loops and then followed by a full `PlayerData` /
  `Finance` / `NeedsDistribution` / `NetworkSoundSystem` burst (734-739), the
  same burst as at join. So 118 is the trigger for that `Finance` resend: the
  client re-sends `Finance` only after a finance event, not every tick.
  What the player did at 22 s is not recorded (no other cause visible in the
  capture), so *what* triggers the +35 mid-game is unknown. Needs a capture
  where the player buys or sells something with a known price.

Next experiment: buy an item with a known cost (e.g. a $X wall/floor tile) and
check whether a 118 with `X` (or a different key like `finance_cost_build`)
appears, and whether `Finance.tr.b` / `v.6` then go *down* by `X`.

### Other event seen: 14

`RaiseEvent` code 14, once (run2 packet 330, 4.7 s in session 7): `04 34 97 80 02 08` ->
`[8427316, 8]` (`8427316 = 0x809734`). It comes in the middle of a `World` /
`ObjectData` loop. Unknown; it could be an object id and a type or a
position packed into one integer. Needs more samples.
