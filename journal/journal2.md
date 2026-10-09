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

## `captures/run3.sqlite`: game speed (Claude Opus 5.5 work)

> **Written by Claude Opus 5.5** from `captures/run3.sqlite`. Not verified by
> hand; items marked *guess* are inference, not observation.

### The capture

19 sessions; the game sessions (`:4531`) are 3, 10, 13, 16 and 19. Session 19
is the last (~36 s) and holds the speed-button spam the user did at the end
(Pause / 1 / 2 / 3 / 4). No new event codes appear anywhere: only 9
(`SystemState`), 118 (once, at join, as in run2) and `SetProperties`.

### Speed is `gt` in the `World` snapshot

The game speed is **not a separate event**. It rides in the `World` system
snapshot (event 9, sent every ~0.35 s), as a field `gt` on two nodes,
`ClientData` and `UniformColourData` (always equal). Session 19, `World` only:

| Packet | t (s) | `gt` | `WorldData.TimeIndex` |
| ------ | ----- | ---- | --------------------- |
| 589-830 | 0.0-10.3 | (absent) | +~0.34 per snapshot |
| 847 | 10.6 | `0` | 701.459 |
| 852-995 | 11.0-16.4 | (absent) | (absent -- frozen) |
| 1007 | 16.8 | `1` | 701.675 |
| 1012 | 17.1 | `2` | 702.225 |
| 1017 | 17.5 | `5` | 703.392 |
| 1021 | 17.8 | `10` | 705.641 |
| 1025 | 18.1 | `5` | 708.815 |
| 1029 | 18.5 | `1` | 710.565 |
| 1037 | 19.2 | `0` | 710.965 |
| 1063-1323 | 19.5-30.3 | `1`/`2`/`5`/`10`, flipping | +0.3 .. +3.5 per snapshot |
| 1342 | 30.5 | `0` | 753.364 |
| 1352-1453 | 30.9-35.6 | (absent) | (absent -- frozen) |

Reading:

- **`gt` is the time multiplier**: `0` = paused, and the four speed buttons
  are **1x, 2x, 5x, 10x** (not 1/2/3/4). `TimeIndex` (game seconds) advances
  by ~0.34 per 0.35 s snapshot at `gt=1`, ~3.0-3.5 at `gt=10`, and stops at
  `gt=0`. `SecondsPlayed` stays real-time (1 per ~1 s) regardless.
  `ObjectId.next` also grows faster at high speed (more objects spawned per
  real second), consistent with "speed only scales the tick rate".
- The snapshot is a **delta**: a field is only written when it changed. Before
  packet 847 `gt` is absent because it never changed from its initial value
  (1 *guess*); while paused, `World` snapshots still go out every ~0.35 s but
  carry no `TimeIndex` (it didn't move) and no `gt` (it didn't change). That
  matches the user's note that packets keep flowing while paused.
- Snapshots are sampled every ~0.35 s, so clicks faster than that are lost:
  the capture only shows the speed at each snapshot, not every click.
  E.g. 17.1 -> 17.5 s jumps `2 -> 5` with no visible `gt` between.
- Why `UniformColourData` carries `gt` too is unclear; it is otherwise the
  prisoner uniform colour table. *guess*: both nodes are client-side UI
  state the host mirrors, and the speed is copied into each.
- The `Intake`, `ObjectData` and `ConstructionSystem` snapshots keep being
  sent at the same rate while paused (each 105x in session 19).

So to **set** the speed from a proxy/bot, one would have to send a `World`
`SystemState` with `ClientData.gt` changed -- there is no dedicated command.
Whether a non-host client can do that (or the host ignores it) is untested.

## `captures/run4.sqlite`: building a concrete foundation (Claude Opus 5.5 work)

> **Written by Claude Opus 5.5** from `captures/run4.sqlite`. Not verified by
> hand; items marked *guess* are inference, not observation.

### The capture

Session 3 is the game (`:4531`, ~14 s). The user placed one concrete
foundation. All 276 `RaiseEvent`s parse once the encoding fixes below are in.
Times are seconds from the start of session 3.

### Encoding fixes (new in this run)

| Where | Bytes | Meaning |
| ----- | ----- | ------- |
| tagged list | `0x0a`-`0x0d` | **negative** int, 1-4 bytes (bit `0x08` = sign): `0b a0 14` = -5280 |
| tagged list | `0x1a` | float32: `1a 00 00 22 42` = 40.5 |
| tree string | length `ff` + int32 | long string; int32 `-1` = **null** (`ActionName`) |

The proxy's `truncated at 41 (wanted 1221952679807963496448 bytes)` errors on
`NetworkSoundSystem`, and the `unknown field type 0x80` errors on `WorkQueue`,
were these.

### The build, step by step

| t (s) | Packet | What | Game action |
| ----- | ------ | ---- | ----------- |
| 5.3-6.3 | 123-139 `PlayerData` | `Job {Type='Foundations', Material=59, PosX/PosY, SizeX/SizeY, Status=1, Cost=...}` | **Dragging the blueprint**: live preview under the cursor. 1x1 = -60, 7x4 = -1180, 17x14 = -5280. |
| 6.4 | 144 `WorkQueue` (new system) | 238 jobs `{Type='Construct', CellX, CellY, MatType='ConcreteFloor'/'BuildingFrame', PlayerIssued=True, ...}` | **Jobs created**: one per tile (17x14 = 238): 143 `ConcreteFloor`, 95 `BuildingFrame`. |
| 6.4-14.2 | `WorkQueue` (91 snapshots) | `<job id> {ObjAssigned.i, ObjAssigned.u}` | **Jobs assigned to workmen**: `.u` = workman uId (8426891-8426901), `.i` = their `ObjectData` index (23-32). |
| 6.7 | 163 `ConstructionSystem` | `Jobs[0] {Type='Foundations', Status=2, Cost=-5280, Speed=238, Counter, FoundationCostSpent}` | **Blueprint on the map**: the placed job. `Counter` goes up to `Speed` (238 = tile count) while `FoundationCostSpent` goes -1630, -2520, -3520, -5040, -5280. |
| 6.7 | 165 `NetworkSoundSystem` | `[0, '_Construction', 'OrderMaterial', x+0.5, y+0.5, 0, 0]` per tile | **Sound**: the order sound at each tile's centre. |
| 7.82 | 274 **event 118** | `[-5280, 'finance_cost_foundations', 0, 0]` | **Cost charged**, once `FoundationCostSpent` reaches `Cost`. |
| 8.02 | 293/294/296/298 | `Jobs[0].Hidden=True`; `Finance.v.6=25110`; sound `[0, '_Finance', 'MakePaymentLarge', 0]`; `World.Balance=25110` | **Balance down** 30390 -> 25110 (exactly -5280), with the payment sound. |
| 10.04 | 327-335 **event 13** | `[8427316, 17, 139]`, then `[8427317..8427320, 26/35/43/44, 2]` | **Materials imported**: 5 objects spawned. |
| 10.37 | 359 `ObjectData` | `17 {a=True, sl0..sl3 = the 4 others}`; `26/35/43/44 {l=True, cr=17/8427316}` | Object 17 (type 139) **carries** the four type-2 objects in slots `sl0`-`sl3`; they are `l`oaded with `cr` (carrier) = 17. |
| 10.42 | 371 `Finance` | `v.3=18840` | Unknown (see below). |

### Magic numbers

| Number / key | Meaning | Confidence |
| ------------ | ------- | ---------- |
| event **13** | **SpawnObject** `[uId, ObjectData index, type]`; `World.ObjectId.next` goes 8427316 -> 8427321 at the same time | observed |
| event **118** | **Cashflow** `[signed amount, ledger key, ?, ?]`; negative = spending | observed |
| `finance_cost_foundations` | ledger key for foundations | observed |
| `Type='Foundations'` | the build tool; `Type=-1` = no tool | observed |
| `Material=59` | concrete (the `WorkQueue` jobs say `MatType='ConcreteFloor'`) | *guess* from co-occurrence |
| `Status` | `-2` no job, `-1` invalid spot (preview red), `1` valid preview, `2` placed | observed |
| `Speed` | the job's tile count (238 for 17x14; 60 for a 1x1 preview) | *guess*; 1x1 says 60, not 1 |
| `Counter`/`Counter2` | progress over the tiles, 0..`Speed`, then restarts with `Hidden=True` | observed |
| `ValidPosSegments [i n] {x, y, 1, 2}` | one row per tile row: from `(x, y)` to `(1, 2)` | observed |
| `QRWallType=46` | unknown; constant | - |
| `PlayerData.p` / `jp` / `js` | cursor position / job position / job size | observed |
| `Finance.v.6` | the bank balance | observed (run2, run4) |
| `Finance.v.3` | unknown; 18840 appears right after the import | - |
| object type **139** | delivery truck | *guess*: it spawns at the map edge (`p` hi 0x55a0 ≈ 85.6) with the 4 materials in its slots |
| object type **2** | a material pallet; `qua` = quantity (20, then 2 and 12), `con` = 79/80 unknown | *guess* |
| sounds `_Construction/OrderMaterial`, `_Finance/MakePaymentLarge`, `_Finance/ReceivePaymentSmall` | `NetworkSoundSystem` cues `[0, bank, name, x, y, ...]` | observed |

### Open questions

- Cost per tile isn't linear (1 -> 60, 28 -> 1180, 238 -> 5280).
- `BuildingFrame` vs `ConcreteFloor`: 95 + 143 = 238, but a 17x14 border is
  58 tiles, so the frame jobs aren't just the edge.
- Run2's event 14 `[8427316, 8]` uses the same uId as this run's truck.
  The ids restart between game loads, so it's a different object. 14 could be
  "despawn".
