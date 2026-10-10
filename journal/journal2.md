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
  | `03` | u8, e.g. colour channels `c1.r` (run6, `EffectsSystem`)            |
  | `04` | string (u8 length)                                                 |
  | `05` | bool (1 byte)                                                      |
  | `06` | u32 length, then a nested tagged list, e.g. `[0, '_Finance', 'ReceivePaymentSmall', 0]` |
  | `07` | double, e.g. `TimeIndex`                                           |
  | `08` | u16                                                                |
  | `09` | int64 (run7, `has` on a type 526 object; always 0 so far)          |

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

## IDA database: how events are dispatched (Claude Sonnet 5.5 work)

Goal: find where the game maps `RaiseEvent` codes (9 `SystemState`, 13, 14,
118...) to handlers, and whether the `SystemState` names (`WorkQueue`,
`Finance`, `PlayerData`...) can tell us the other codes.

### Setup

`Prison Architect64.exe.i64` (IDA 9.0, 60,266 functions, 22,960 strings) was
opened headlessly with idalib on a **copy** (`../ida-work/db/pa.i64`, outside
the repo; the original has unpacked `.id0` files next to it, so IDA probably
has it open). idalib only works with **Python 3.11** here (`py -3.11`; the
module is called `ida`, not `idapro`). Scripts are in `../ida-work/scripts`
(`dump.py`, `dec.py`, `renames.py`, `apply.py`); `../ida-work/out/dump.json`
has all function names and strings.

### Findings

- **The `SystemState` names are not a dispatch table.** `WorkQueue`,
  `Finance`, `PlayerData`, `Intake`, `Research`... are the *save-file section
  names* (e.g. `0x140abd8f0 Research`, `0x140ad04b8 Finance`). Each is
  referenced by many unrelated functions (save/load, UI, per-system code), and
  no single function references them all. Their address order is just the
  string pool, so it tells us nothing about codes. The network snapshot is the
  save-file tree, which is why they match.
- **There is no switch on the event code either.** `ExitGames::LoadBalancing::
  Client::onEvent` (`0x140843900`) handles the Photon built-ins (0, 3, 4, 6, 9,
  10, 30, 33, 34, 35) and sends everything else (`default:`) to the listener:
  `listener->customEventAction(playerNr, eventCode, content)`, vtable +48.
  The game's listener is `PhotonInterfaceOld` (also `PhotonInterfaceNew`, a
  second wrapper that queues calls onto another thread).
  `PhotonInterfaceOld::customEventAction` (`0x14012BFB0`) looks the event code
  up in a `std::map<int, handler>` at `this+104`. A miss logs
  **`Trying to invoke unregistered RPC: %d`**. So the codes are **RPC ids
  registered at runtime**, not a compiled switch. (CORRECTION, see Mistakes log: the `case` numbers in `onEvent`'s decompile
  are an offset index, not wire codes; Photon's built-in events are 224-255, so
  game codes 0-143 never collide with them.)
- **Next step:** find the code that inserts into that map (`this+104`) and read
  the ids it registers. Candidates: callers of the vtable methods around
  `PhotonInterfaceOld`'s main vtable (`0x140ab1f48`) and
  `sub_1401338F0`/`sub_140126750`, which also call `queueRPCHandlerCall?`
  (`0x1401271A0`). The registrations should list every code with its handler.

### Renames applied to the copy

`../ida-work/scripts/renames.py` (idempotent; run it in IDA to apply to the
real `.i64`). Convention: C++ `Class::method` like the existing
`ExitGames::...` names; `?` = unsure, `???` = really unsure.

| Address | Name |
| ------- | ---- |
| `0x140843900` | `ExitGames::LoadBalancing::Client::onEvent` (already named) |
| `0x14012BFB0` | `PhotonInterfaceOld::customEventAction` |
| `0x14012C180` | `PhotonInterfaceOld::joinRoomEventAction?` |
| `0x1401271A0` | `PhotonInterfaceOld::queueRPCHandlerCall?` |
| `0x1407C8320` / `0x1407C9D60` | `SaveGame::writeSystemSections???` / `readSystemSections???` (use the section names; not network) |
| `0x1406D7F00` | `ReformProgram::serializeDefinition??` |
| `0x1403CC960` | `PlayerDataSystem::handleState???` |

Only analysed functions were renamed; the other ~55,000 `sub_*` are untouched.

### `customEventAction` is the interesting function

`PhotonInterfaceOld::customEventAction` (`0x14012BFB0`, listener vtable
`0x140ab1e50` slot 6) is the single choke point for every game `RaiseEvent`
the client *receives* (everything `Client::onEvent` doesn't consume).
Worth coming back to because:

- It is where the event code (the `Code (244)` param, our 9 / 13 / 14 / 118)
  becomes a handler call. It looks the code up in a `std::map<int, handler>` at
  `this+104`; a miss logs `Trying to invoke unregistered RPC: %d`. So the
  full list of event codes = the ids registered into that map.
- Its `content` argument is the `Data (245)` payload (the tagged value list).
  The handler gets the args already parsed (`sub_14083B280/B290` read
  value count and type), so this is also the reference for the tag format.
- The same RPC machinery has a sibling for the sending side, a
  `PhotonNetworkingManager::CanSendRPC` check, and a second implementation
  (`PhotonInterfaceNew` / `QueuedRPCInterface`) that queues calls to another
  thread, so there are at least two code paths to keep in mind.
- The game also has an **RPC id -> name table**: `sub_1403E48A0` returns
  `byte_140DB9640[32 * id]` (a `std::string`, ids 0..0x8F = 144 entries, else
  `UnknownRPC(%d)`). It is filled at startup by static initialisers, so the
  names are one decompile away. That would give names for every code.

### The RPC table: every event code, with its name

`sub_1403E48A0` (now `RPC::getName?`) indexes a table of 144 `std::string`s at
`0x140DB9640`; the static initialiser `0x140030E20` (`RPC::initNames?`) fills
it. **The index is the wire event code** (`Code (244)`). Names and ids
extracted verbatim from the decompile (`../ida-work/out/rpc_names.json`):

| | | | |
| --- | --- | --- | --- |
| 0 `None` | 1 `SetNumSaveDataChunks` | 2 `SaveDataChunkAck` | 3 `SaveDataChunk` |
| 4 `ProcessingStarted` | 5 `AuthoriseConnection` | 6 `KickPlayer` | 7 `IncorrectPassword` |
| 8 `SendingSaveGame` | 9 `DirectoryData` | 10 `LandPurchased` | 11 `LogObjectsFromIndex` |
| 12 `FirstQueued` | 13 `ObjectAdded` | 14 `ObjectRemoved` | 15 `CreateRoom` |
| 16 `RemoveRoom` | 17 `PowerCellModified` | 18 `WaterCellModified` | 19 `WaterCellCleared` |
| 20 `RPCWaterValveChanged` | 21 `ObjectiveRemoved` | 22 `MarkerCreatedId` | 23 `MarkerCreatedPos` |
| 24 `SectorZoneChange` | 25 `GangSegregationChange` | 26 `SectorAccessOnlyChange` | 27 `SectorJobCountChange` |
| 28 `SectorAddTarget` | 29 `SectorClearTargets` | 30 `ChosenScheduleChange` | 31 `GuardDeploymentChange` |
| 32 `PlanningJobChange` | 33 `PlayerSetsTarget` | 34 `ElectricalSwitch` | 35 `PerformAction` |
| 36 `BeginResearch` | 37 `ToggleResearchDesired` | 38 `ApplyPrisonerCategory` | 39 `ApplyPunishment` |
| 40 `ClearAllPunishments` | 41 `ActivateInformant` | 42 `DeactivateInformant` | 43 `NewVehicleCallout` |
| 44 `SquadDismissal` | 45 `SackStaff` | 46 `ApporveTransfer` | 47 `AcceptGrant` |
| 48 `CancelGrant` | 49 `IncreaseLoan` | 50 `DecreaseLoan` | 51 `SellShares` |
| 52 `BuyBackShares` | 53 `SetRegime` | 54 `EvictGangTerritory` | 55 `CrisisButtonClicked` |
| 56 `FiremanAimHose` | 57 `FireInformant` | 58 `TransferAllowedChange` | 59 `TransferChange` |
| 60 `TransferAmountChange` | 61 `PolicyChange` | 62 `PrivilegePolicyChange` | 63 `MealPolicyChange` |
| 64 `ParoleRateChange` | 65 `UseCellQualityChange` | 66 `StaffPayModifierChange` | 67 `StaffMaxBreakChange` |
| 68 `SentencesEnabledChange` | 69 `ExtensionCriteriaChange` | 70 `ExtensionCriteriaValueChange` | 71 `ExtensionCriteriaMetChange` |
| 72 `ReductionCriteriaChange` | 73 `ReductionCriteriaValueChange` | 74 `ReductionCriteriaMetChange` | 75 `NeedsDistributionUpdate` |
| 76 `EntityUpdateRequest` | 77 `IntakeRatioChange` | 78 `IntakeTypeChange` | 79 `IntakeNumTotalChange` |
| 80 `IntakeTimeChange` | 81 `IntakeRestrictionsChange` | 82 `StartReformProgram` | 83 `StopReformProgram` |
| 84 `RunReformScheduler` | 85 `ScheduleProgram` | 86 `SetProgramManual` | 87 `LandPurchaseRequest` |
| 88 `TriggerSoundEvent` | 89 `TriggerPositionedSoundEvent` | 90 `TriggerObjectSoundEvent` | 91 `TriggerObjectCustomSoundEvent` |
| 92 `WiredObjectConnect` | 93 `WiredObjectClear` | 94 `WireDataRequested` | 95 `StopAllSounds` |
| 96 `GameSpeedChange` | 97 `TreeAgeChange` | 98 `DeliveryStopSetAllowed` | 99 `DeliveryStopSetOverall` |
| 100 `DeliveryStopAssignZone` | 101 `DeliveryStopClearAllZones` | 102 `FarmingPolicy` | 103 `AddRoomCropDist` |
| 104 `RemoveRoomCropDist` | 105 `LockPercentagesCropDist` | 106 `ChangePercentagesCropDist` | 107 `RoomConnectionToggled` |
| 108 `LogicCircuitChange` | 109 `LabourManagementChanged` | 110 `SpawnObject` | 111 `CoveragePlanChanged` |
| 112 `CoveragePlanEmergencyChanged` | 113 `WaterCellFrozen` | 114 `WaterCellInsulated` | 115 `WaterCellFlood` |
| 116 `PrisonerWageChanged` | 117 `NewSpeechAdded` | 118 `TransactionAdded` | 119 `TransactionAppended` |
| 120 `CommitBuildPlanning` | 121 `VisitationRateChange` | 122 `IntakeNumPerDayChange` | 123 `LightningStrike` |
| 124 `ToggleFogOfWar` | 125 `IntakeTogglePrisonerReplacement` | 126 `RemovePrisoner` | 127 `AssignGuardToPrisoner` |
| 128 `UnassignGuardFromPrisoner` | 129 `MarkingTypeChanged` | 130 `RestrictAccessSettingsChanged` | 131 `PrisonerCategoryChanged` |
| 132 `QuickCellChange` | 133 `CrisisCustomSearchArea` | 134 `CrisisCustomSaveSchedule` | 135 `RegisterInformant` |
| 136 `ChangeRank` | 137 `ToggleStaffKeys` | 138 `Distortion` | 139 `ToggleAllowStunBatons` |
| 140 `ControlAdvancedSearchLight` | 141 `AimAdvancedSearchLight` | 142 `EquipPrisonerTrackingBelt` | 143 `LastQueued` |

Checks against the captures:

- **13 `ObjectAdded`**, **14 `ObjectRemoved`**: match run4's "spawn" `[uId,
  ObjectData index, type]` and run2's `[8427316, 8]` ("despawn" guess was
  right). Note 110 `SpawnObject` is a *different* id; the "SpawnObject" label in
  run4 should be `ObjectAdded`.
- **118 `TransactionAdded`**: the cashflow event `[amount, ledger key, ?, ?]`
  (`119 TransactionAppended` probably extends one).
- **9 `DirectoryData`**: our `SystemState` (`[system name, snapshot]`).
  Plausible (it carries the per-system state), less certain than the others.
- 0..8 look like the join handshake (`SetNumSaveDataChunks`,
  `SaveDataChunk(Ack)`, `AuthoriseConnection`, `SendingSaveGame`...);
  `96 GameSpeedChange` is probably what run3's speed changes *should* have
  used, but run3 saw none (speed is in `ClientData.gt`), so it may be unused.
  `143 LastQueued` / `12 FirstQueued` bracket the ids that go through the
  queue.
- Ids above 143 don't exist (`UnknownRPC(%d)`).

### Where they're registered

- `PhotonInterfaceOld::registerRPC` (`0x14012B8B0`) / `unregisterRPC`
  (`0x14012B9C0`) insert/erase in the map; `PhotonInterfaceNew` has queued
  twins (`0x1401262C0` / `0x1401263E0`).
- Each handler is a small typed wrapper (e.g. `sub_1403D5030`) around the real
  callback: it checks the payload shape, calls the callback via a
  `std::function`, and otherwise logs `ERROR: Failed to unserialise remote call
  to %s (%d)`. About 50 of them sit between `0x1403BE7E0` and `0x1403DD020`,
  one per RPC. Next: map each wrapper to its id (its `a1+8`) to get the payload
  shapes (e.g. what `ObjectAdded` carries) straight from the code.

## Mistakes log (Claude Sonnet 5.5, IDA session)

What went wrong, so we don't repeat it:

- **Assumed the `SystemState` names were a dispatch table** (user's idea, I
  went along). They are save-file section names; I spent several steps on
  xrefs before checking what the strings were used for. *Look at the first
  1-2 decompiled users of a string before building theories on its order.*
- **Assumed a `switch` on the event code existed** and wrote an immediate-value
  scanner for `0x76`/`9`. It found one unrelated function. The real design is a
  runtime `std::map` (RPC registration). *Read the receiver's decompile before
  scanning for patterns.*
- **Wrongly read `onEvent`'s `case 9`** as "code 9 is a Photon built-in" and put
  that in this journal (now corrected above). Hex-Rays prints the switch *index*
  after subtracting a base; Photon built-ins are 224-255. *Check the
  subtraction before quoting case labels as wire values.*
- **Environment guesses**: expected the module to be `idapro` (it is `ida` in
  this 9.0 build); expected Python 3.14 to work (idalib bindings need 3.11);
  trusted `py -0` for 3.12, which wasn't actually installed. *Run
  `py -V:x -c ...` before relying on a listed interpreter.*
- **Tool slips**: called `Grep` from PowerShell; put a quoted Python one-liner
  through PowerShell (quote error; use a script file); dumped ~25 full vtables
  to the terminal (use a filter).
- **First type scan matched demangled `RPC<`, but the names are stored
  mangled** (`??_7?$RPC@`); found 0 vtables. Then my id regex expected bare
  digits but IDA prints `65LL`, and some ids sit in `vNN` variables. *Print
  three raw samples before writing the regex.* Also not using IDA's demangler
  (`idc.demangle_name`) from the start cost a round trip (user pointed it out).
- **Overclaiming in the summary**: said "I'll map each wrapper to its id" as
  if wrappers carried ids; the id is stored by the `RPC<...>` constructor and
  passed at the registration call site, so the unit of work was the
  *registrar*, not the wrappers.

### Argument shapes (how the handlers are typed)

Each id is registered with an `RPC<T1, T2, ...>` template instantiation
(`sub_1403C11D0` is the registrar: 118 constructor calls, `RPC<...>` ctor
takes `this+8 = id`). The template arguments are the payload types, in wire
order. Result, now in `pa_rpc_data.py` (generated; 141 of 144 ids have a shape,
the other three are the sentinels `None`, `FirstQueued`, `LastQueued`):

| id | name | argument types |
| -- | ---- | -------------- |
| 0 | `None` | (none) |
| 1 | `SetNumSaveDataChunks` | int, int |
| 2 | `SaveDataChunkAck` | (none) |
| 3 | `SaveDataChunk` | MemoryBlock |
| 4 | `ProcessingStarted` | (none) |
| 5 | `AuthoriseConnection` | string |
| 6 | `KickPlayer` | (none) |
| 7 | `IncorrectPassword` | (none) |
| 8 | `SendingSaveGame` | (none) |
| 9 | `DirectoryData` | string, MemoryBlock |
| 10 | `LandPurchased` | (none) |
| 11 | `LogObjectsFromIndex` | int |
| 12 | `FirstQueued` | (none) |
| 13 | `ObjectAdded` | ObjectId, int |
| 14 | `ObjectRemoved` | ObjectId |
| 15 | `CreateRoom` | ObjectId, int |
| 16 | `RemoveRoom` | ObjectId |
| 17 | `PowerCellModified` | int, int, int |
| 18 | `WaterCellModified` | int, int, int, bool |
| 19 | `WaterCellCleared` | int, int, bool |
| 20 | `RPCWaterValveChanged` | int, int, bool |
| 21 | `ObjectiveRemoved` | string, bool |
| 22 | `MarkerCreatedId` | ObjectId, int |
| 23 | `MarkerCreatedPos` | WorldPosition, int |
| 24 | `SectorZoneChange` | int, int, CustomSectorNetworkData |
| 25 | `GangSegregationChange` | int, int |
| 26 | `SectorAccessOnlyChange` | int, bool |
| 27 | `SectorJobCountChange` | int, int |
| 28 | `SectorAddTarget` | int, int |
| 29 | `SectorClearTargets` | int |
| 30 | `ChosenScheduleChange` | int, int |
| 31 | `GuardDeploymentChange` | int, int, int, int |
| 32 | `PlanningJobChange` | int, int, int, int, Vector2, int, int |
| 33 | `PlayerSetsTarget` | int, Vector2, bool, ObjectId |
| 34 | `ElectricalSwitch` | int, bool |
| 35 | `PerformAction` | ObjectId, int |
| 36 | `BeginResearch` | int |
| 37 | `ToggleResearchDesired` | int |
| 38 | `ApplyPrisonerCategory` | ObjectId, int |
| 39 | `ApplyPunishment` | ObjectId, int, int |
| 40 | `ClearAllPunishments` | ObjectId |
| 41 | `ActivateInformant` | ObjectId, bool |
| 42 | `DeactivateInformant` | ObjectId, bool |
| 43 | `NewVehicleCallout` | int |
| 44 | `SquadDismissal` | ObjectId |
| 45 | `SackStaff` | ObjectId |
| 46 | `ApporveTransfer` | ObjectId |
| 47 | `AcceptGrant` | string |
| 48 | `CancelGrant` | string |
| 49 | `IncreaseLoan` | (none) |
| 50 | `DecreaseLoan` | (none) |
| 51 | `SellShares` | int |
| 52 | `BuyBackShares` | int |
| 53 | `SetRegime` | int, int, int |
| 54 | `EvictGangTerritory` | ObjectId |
| 55 | `CrisisButtonClicked` | int, int, bool |
| 56 | `FiremanAimHose` | ObjectId, Vector2 |
| 57 | `FireInformant` | ObjectId |
| 58 | `TransferAllowedChange` | bool, int |
| 59 | `TransferChange` | int, bool, int |
| 60 | `TransferAmountChange` | int, int, int |
| 61 | `PolicyChange` | int, MisconductPolicy, int |
| 62 | `PrivilegePolicyChange` | int, int, bool |
| 63 | `MealPolicyChange` | int, int, int |
| 64 | `ParoleRateChange` | int, int |
| 65 | `UseCellQualityChange` | bool |
| 66 | `StaffPayModifierChange` | float |
| 67 | `StaffMaxBreakChange` | int, int |
| 68 | `SentencesEnabledChange` | bool |
| 69 | `ExtensionCriteriaChange` | int, bool |
| 70 | `ExtensionCriteriaValueChange` | int, int |
| 71 | `ExtensionCriteriaMetChange` | int |
| 72 | `ReductionCriteriaChange` | int, bool |
| 73 | `ReductionCriteriaValueChange` | int, int |
| 74 | `ReductionCriteriaMetChange` | int |
| 75 | `NeedsDistributionUpdate` | bool, int |
| 76 | `EntityUpdateRequest` | ObjectId |
| 77 | `IntakeRatioChange` | int, float |
| 78 | `IntakeTypeChange` | int |
| 79 | `IntakeNumTotalChange` | int |
| 80 | `IntakeTimeChange` | int |
| 81 | `IntakeRestrictionsChange` | bool |
| 82 | `StartReformProgram` | int, bool |
| 83 | `StopReformProgram` | int |
| 84 | `RunReformScheduler` | (none) |
| 85 | `ScheduleProgram` | int, int, int, ObjectId |
| 86 | `SetProgramManual` | int, bool |
| 87 | `LandPurchaseRequest` | int, int, int, int, bool, bool |
| 88 | `TriggerSoundEvent` | SoundConstraint, string, string, NetworkSoundId |
| 89 | `TriggerPositionedSoundEvent` | SoundConstraint, string, string, Vector3, NetworkSoundId |
| 90 | `TriggerObjectSoundEvent` | SoundConstraint, SoundObjectId, string, NetworkSoundId |
| 91 | `TriggerObjectCustomSoundEvent` | SoundConstraint, SoundObjectId, string, string, NetworkSoundId |
| 92 | `WiredObjectConnect` | ObjectId, ObjectId |
| 93 | `WiredObjectClear` | ObjectId |
| 94 | `WireDataRequested` | (none) |
| 95 | `StopAllSounds` | NetworkSoundId |
| 96 | `GameSpeedChange` | int |
| 97 | `TreeAgeChange` | ObjectId, int |
| 98 | `DeliveryStopSetAllowed` | ObjectId, int, bool |
| 99 | `DeliveryStopSetOverall` | ObjectId, int, bool |
| 100 | `DeliveryStopAssignZone` | ObjectId, ObjectId, int |
| 101 | `DeliveryStopClearAllZones` | ObjectId |
| 102 | `FarmingPolicy` | bool, int, int, int, int, float |
| 103 | `AddRoomCropDist` | ObjectId, ObjectId |
| 104 | `RemoveRoomCropDist` | ObjectId, ObjectId |
| 105 | `LockPercentagesCropDist` | ObjectId, int, int |
| 106 | `ChangePercentagesCropDist` | ObjectId, int, int, float |
| 107 | `RoomConnectionToggled` | ObjectId, ObjectId |
| 108 | `LogicCircuitChange` | ObjectId, int |
| 109 | `LabourManagementChanged` | ObjectId, int, int |
| 110 | `SpawnObject` | int, int, int, int, int |
| 111 | `CoveragePlanChanged` | int, bool, bool |
| 112 | `CoveragePlanEmergencyChanged` | int, int, bool, int, int, int |
| 113 | `WaterCellFrozen` | int, int, bool, bool |
| 114 | `WaterCellInsulated` | int, int, bool |
| 115 | `WaterCellFlood` | int, int, int, float |
| 116 | `PrisonerWageChanged` | int, float |
| 117 | `NewSpeechAdded` | int, string |
| 118 | `TransactionAdded` | int, string, signed char, string |
| 119 | `TransactionAppended` | int, string, signed char, string |
| 120 | `CommitBuildPlanning` | int, int |
| 121 | `VisitationRateChange` | int, int |
| 122 | `IntakeNumPerDayChange` | int |
| 123 | `LightningStrike` | int, Vector2, float |
| 124 | `ToggleFogOfWar` | bool |
| 125 | `IntakeTogglePrisonerReplacement` | (none) |
| 126 | `RemovePrisoner` | ObjectId |
| 127 | `AssignGuardToPrisoner` | ObjectId |
| 128 | `UnassignGuardFromPrisoner` | ObjectId |
| 129 | `MarkingTypeChanged` | ObjectId, int, int |
| 130 | `RestrictAccessSettingsChanged` | ObjectId, bool, bool |
| 131 | `PrisonerCategoryChanged` | ObjectId, int |
| 132 | `QuickCellChange` | ObjectId, ObjectId |
| 133 | `CrisisCustomSearchArea` | int, int, bool |
| 134 | `CrisisCustomSaveSchedule` | int, int, int, int, int |
| 135 | `RegisterInformant` | ObjectId |
| 136 | `ChangeRank` | ObjectId, int |
| 137 | `ToggleStaffKeys` | bool |
| 138 | `Distortion` | ObjectId |
| 139 | `ToggleAllowStunBatons` | bool |
| 140 | `ControlAdvancedSearchLight` | ObjectId |
| 141 | `AimAdvancedSearchLight` | ObjectId, Vector2 |
| 142 | `EquipPrisonerTrackingBelt` | ObjectId |
| 143 | `LastQueued` | (none) |

Notes:

- `ObjectId` = **two** wire values (uId, ObjectData index): `ObjectAdded` is
  `ObjectId, int` = `[uId, index, type]`, as seen in run4.
- `TransactionAdded` is `int, string, signed char, string`: amount, ledger key,
  a small int, a string (both were `0, ''` in the captures).
- `DirectoryData` (our `SystemState`) is `string, MemoryBlock`: system name +
  the zlib snapshot, so `MemoryBlock` = one byte string.
- Composite arities for `Vector2`, `WorldPosition`, `Vector3`,
  `NetworkSoundId`... are *not read from the binary yet*; they are being
  measured from the captures (see `pa_rpc.COMPOSITE_ARITY`).
- Deserialisers come in two flavours: old ones check raw tags (e.g. tag 26 =
  int32, `<= 1` for bool) and newer ones use a reader that returns the compact
  tagged ints our `decode_args` handles. Both appear in the same table.

### Plan: bot actor

`../photon-realtime-py` already has `RealtimeClient.op_raise_event(code, data,
...)` with an e2e test, so a bot = connect, join the room, then
`op_raise_event(code, pa_rpc.build(code, ...))`. Steps: (1) `pa_rpc`
(parse/build/format) - in progress; (2) show typed RPCs in the proxy view;
(3) `bot.py`: join a room as a second actor and send e.g. `GameSpeedChange`,
`ObjectAdded`... Check first that `Data` goes out as a byte array
(`Int8SliceParameter`), not a Photon dict/string.

### `pa_rpc.py`: typed codec (Haiku agent, reviewed)

`pa_rpc.parse / build / format_rpc / encode_args` (+ `tests/test_pa_rpc.py`).
`encode_args` is the exact inverse of `decode_args` on every captured payload
(1,485 event payloads over run1-run4). The captures only contain **4 of the 144
codes** (9, 13, 14, 118), and every observed value count matches the declared
types. Everything else is from the binary, not yet seen on the wire.

Measured / pinned arities: int, string, signed char, MemoryBlock = 1 value,
ObjectId = 2. Left unknown (`None`, so `build`/`parse` refuse them rather than
guess): `Vector2`, `Vector3`, `WorldPosition`, `MisconductPolicy`,
`SoundConstraint`, `SoundObjectId`, `NetworkSoundId`, `CustomSectorNetworkData`.
That blocks building the RPCs that use them (e.g. `ObjectAdded` is fine, but
`FiremanAimHose` (`ObjectId, Vector2`), `MarkerCreatedPos`, the sound RPCs and
`SectorAddTarget` are not).

Finding: `TransactionAdded`'s last argument is declared `string` but arrives as
int `0` in all 8 captures, so an **empty string is sent as `0x00`** (not
`0x10`). I changed the encoder to match after the agent guessed `0x10`.

Review notes: the agent's tests initially encoded `0x10` for an empty string
(unverified guess, now fixed); `parse`/`build` check value *counts* and
composite shapes but not per-kind types, because a strict check would have
rejected real 118 payloads.

### Mistakes log (continued)

- **Briefed the agent with `build(118, ..., b'')`** from the declared type
  without checking the capture, where the slot was `0`. The agent caught it;
  I should have read the captured bytes myself before writing the brief.
- **Expected agent 1 to be able to pin Vector2 etc.** from the captures; only
  4 of 144 codes appear in them. The unknown arities need either IDA (read the
  `RPC<...>` serialisers for those types) or new captures that exercise those
  actions.

### Wire format of `bool` (from the binary, not in any capture)

The deserialiser of an RPC with a bool (`sub_1403DB5D0`, `bool,int`) reads the
first byte raw: `0` = false, `1` = true, anything else (incl. -1) = error
("Failed to unserialise remote call"). It then reads the int with the usual
tagged reader (`sub_140134870`). So a bool is a single byte `00` / `01`.
Consequence: `decode_args` reads tag `0x01` as an integer in 0 bytes = **0**,
so `true` decodes as 0, and `encode_args(True)` (-> `02 01`) would be rejected
by the game. Fix must be typed (decide by the declared type), because `01` as
a *non-bool* is not valid anyway. Float: tag `0x1a` + float32 (the `float`
deserialiser checks tag 26 = 0x1a and reads 4 bytes after it).

Also: the first attempt to tie each `RPC<...>` type to its wrapper by "the
function its vtable slot calls" was wrong for several types (the slot-4 target
of `RPC<ObjectId,Vector2>` turned out to be the `bool,int` wrapper). Wrappers
are shared/templated by argument *kind*, so wrapper -> type is not 1:1; only
the `RPC<...>` ctor + id registration is reliable.

### Status after the first implementation round

- `pa_rpc_data.py` (generated table), `pa_rpc.py` (typed `parse` / `build` /
  `format_rpc`, bool as a raw byte), `pa_events.py` (proxy view uses the game's
  names; `SystemState` / `SpawnObject` / `Cashflow` kept as filter aliases).
  39 tests, ruff format + the CI lint selection clean.
- Checked end to end: all 1,475 captured events (run1-run4: code 9 x1461,
  13 x5, 14 x1, 118 x8) pass through `format_event`, `packet_label` and
  `log_lines` with no "unparsed" fallback.
- Cash-flow line now reads `amount +35 (int 0, string '')`.
- **Still unknown / blocking some `build()` calls**: arities of `Vector2`,
  `Vector3`, `WorldPosition`, `MisconductPolicy`, `SoundConstraint`,
  `SoundObjectId`, `NetworkSoundId`, `CustomSectorNetworkData` (the code refuses
  rather than guesses). Float/bool encodings come from the binary only; no
  capture exercises them.
- **Not done**: the bot (`bot.py`). Needs (1) the arities above for the RPCs we
  want to send, (2) confirmation that `op_raise_event` sends `Data` as a byte
  array, and (3) a live game room to try it against.

### Mistakes log (continued)

- **Delegated before reading the evidence**: the brief for agent 1 asserted
  `build(118, ..., b'')`, which the captures contradict (that slot is int `0`).
  The agent caught it.
- **Let two agents touch related files in one window**: agent 1's rewrite of
  `pa_rpc.py` broke agent 2's tests for a few seconds (a removed import).
  Harmless here, but sequence them next time, or give each a disjoint module
  with a frozen interface.
- **My own bool bug report came from reading one wrapper**; I only found it
  because I read a deserialiser body instead of trusting a type table. The
  codec had round-tripped every capture and still had a latent wire bug, so
  *capture round trips don't prove coverage; check which codes they exercise.*

## Bot TUI (Claude Sonnet 5.5 work)

**Built**: `bot.py` (typer + InquirerPy + a prompt_toolkit slider) and
`tests/test_bot.py` (28 tests, no network). 67 tests pass in the repo.

**Run**: `python bot.py` (interactive: region -> lobby -> game -> menu),
`python bot.py regions` (read-only list), options `--region`, `--app-id`
(env/.env `PHOTON_APP_ID`), `--app-version` (default `the_slammer_1.0`, read from
the Authenticate packets in `captures/run1.sqlite`), `--name-server` (env
`PHOTON_NAME_SERVER`; `host[:port]` or `auto`), `--speed-index`, `--verbose`.
The local proxy's hosts redirect makes the default name server unusable, so pass
the real IP. The game's real name server is `ns.exitgames.com`
(`prison_architect.resolve_upstream`, which `auto` calls), not
`ns.photonengine.io`, which is only the library default. The game's own App ID is
`prison_architect.PRISON_ARCHITECT_APP_ID`; only that id lists the game's rooms.

**Design**: `Session` runs `client.service()` in a daemon thread; every client
call takes one `RLock`; prompts run in the main thread. Ctrl-C anywhere ->
`Session.stop()` (disconnect, brief flush, join). Regions: the library
auto-pings and auto-picks when no `fixed_region` is set, so `on_region_list_received`
sets `client.cloud_region` to a sentinel to suppress the pinger, we read the list,
disconnect, and use a second client with `fixed_region` for the real session.
Lobbies come from `enable_lobby_statistics` (default lobby always offered);
games from `client.room_list` after `op_join_lobby`. `ACTIONS` is the registry of
`(label, handler(Context))` for more RPCs. Handshake RPCs 0..9 are only tagged
`[handshake]` in the event stream; DirectoryData (9) is one line unless `--verbose`.

**How bytes are sent**: `op_raise_event(96, data)` with `data: bytes` works as is.
`to_param(bytes)` gives `Int8SliceParameter`, the code goes as `Int8Parameter`
under key 244 and the data under 245. Verified against the library's local
`PhotonServer` (scripts in `ida-work/scripts/bot_local_*.py`): a second client got
back `b'\x02\x05'` for `build(96, 5)` and the captured events 13 and 9 formatted
correctly. Default receivers are "Others"; which receiver group the game wants is
unknown.

**UNVERIFIED**: the int in `GameSpeedChange(96)`. Default sends the multiplier
(0/1/2/5/10, the same values as `ClientData.gt`); `--speed-index` sends the stop
index 0..4. One mapping function, `speed_wire_value`, and the UI prints what was
sent. No capture contains code 96 and I never talked to a live game.

**Surprises**: the library README says `SerializationProtocol.V16`, the enum is
`V6/V7/V8`. The game speaks 1.6 (capture `protocol` column is 6); the bot keeps the
library default 1.8, which the README says can share a room. Not tested against the
game. The captures show the game on TCP ports 4533/4530/4531. The group callback of
a typer app runs before `regions --help`, so the App ID check lives in the commands.

**Not verified**: the InquirerPy menus (no console in my shell; only the slider was
driven, with a pipe input), the real Photon cloud (no App ID in env), the join
handshake (RPCs 0..8 not implemented; the bot just joins the Photon room).

**Mistakes / dead ends**
- Used `console.print` with `[label]` text: rich ate it as markup. Use `markup=False`
  for anything that is data.
- Wrote the slider with separate dot and label spacing, so the dots drifted off
  their labels; rebuilt it as equal-width cells (dot centred in the cell).
- Patched files with Python heredocs containing `\n` escapes through the shell: the
  escapes became real newlines and broke the file. Use the editor tool.
- The group callback validated the App ID, which broke `regions --help`.
- First local test used a fake app id; the library's server wants 32 characters.
- `render_slider` first took the (label, value) tuples and a list of labels; keep
  it to labels only.

## Live test: mini bot joins a hosted game (run5)

Setup: real client hosted room `A` (region `au`, password `123`, actor `Noob`)
through the proxy with `--record captures/run5.sqlite`; the live capture was
readable while recording (1,418 packets seen within a minute).

- **What the game sends to create a room** (CreateGame, op 227): name `A`;
  room props `{MAS: 'Noob' (master/host name), PA: True}`, listed in the lobby
  (`250 = [MAS, PA]`), max players `4` (`255` in the room-options map); player
  props `{255: 'Noob', P: 300 (ping), C: '0xe5bc7eff' (colour)}`. App version
  `the_slammer_1.0`, region `au`, auth with the game's app id (not recorded
  here). The Name Server reply lists regions `eu us usw asia au` and per-region
  Master addresses.
- **Mini bot** (`../ida-work/scripts/minibot.py`, built on the new
  `pyPhotonRealtime` client): connected through the proxy (hosts redirect ->
  127.0.0.1), joined the lobby, saw `'A' 1/4 open=True props={'PA': True,
  'MAS': 'Noob'}`, joined the room with player prop `255 = 'Bot'` and received
  the host's stream of `RPC 9 DirectoryData` (`Intake`, `MisconductSystem`,
  `World`, `CellData`, `ObjectData`, `ConstructionSystem`, `NetworkSoundSystem`,
  `Contraband`...) decoded by `pa_rpc`. **No password was needed at the Photon
  level**; if the game checks `123`, it does so in its own RPCs
  (`AuthoriseConnection`/`IncorrectPassword`) - not exercised yet.
- Not sent yet: any game RPC (speed etc.).
- Observed: joining without the handshake did not get the bot kicked within
  ~8-15 s, and the host kept broadcasting state to it.

### Mistakes log (continued)

- Ran the bot script with `python -I`, which ignores the editable install path
  (`ModuleNotFoundError: pyphotonrealtime`). `-I` is for *untrusted* data
  scripts; for our own tooling that imports the repo, run plain `python`.

### Bot identity and ping (live-tested on run5)

- **Name**: the actor name is player property `255` with an **`Int8Parameter`
  key**. Passing `{255: "Claude"}` in `EnterRoomParams.player_properties` sent an
  `Int32Parameter(255)` key, so the game showed a nameless player. Setting
  `client.local_player.nick_name` makes the library build the right key (and
  `bot.py` now has `--name`, default `Claude`).
- **Colour**: property `C`, a *string* `0xRRGGBBAA` (alpha `ff`). The bot sends
  Claude's orange `0xd97757ff` in the join properties (`--colour`).
- **Ping**: the game shows `?` until it receives `SetProperties` (op 252) with
  `{P: <ms>}` for the actor (`ActorNr` = our actor number, `Broadcast` = True).
  The real client sends one ~1.3 s after joining, then every ~4.0 s. The value is
  Photon's smoothed round-trip time (~335 ms to the AU Game Server from the
  user's machine; the bot measured 339-355 ms to the same server).
  Gotchas: the library only measures a round trip from keep-alive pings, which
  it sends when idle (every 2 s by default), so `peer.round_trip_time` was `0`
  and the first `P` was `0`. `bot.Session` now sets `keep_alive_interval = 1.0`
  and holds the first `P` until `last_round_trip_time` exists
  (`Session.report_ping`, unit-tested).
- Verified live through the real `Session` code path (not only the mini bot):
  `SetProperties` `{P: 340..355}` for actor 4 every 4 s in run5.
- Not verified: the real client also sends ~1,800 tiny (5-byte) client -> server
  packets with no op code in run5's Game Server session, ~50 per second at
  times. I did not decode them or try to reproduce them (possibly transport
  keep-alive/ack framing). If the game turns out to expect more from a "real"
  client, start there.

### Mistakes log (continued)

- **Wrong key type for a Photon property**: `255` as a Python int became
  `Int32Parameter`; the protocol wants `Int8Parameter` for the well-known actor
  property keys. The captured packet (`Int8Parameter(255)`) showed it; I only
  looked after the user reported the missing name. *Diff our packet's parameter
  *types* against the real client's, not just the values.*
- **Missed the periodic `P`**: the journal already said `P` is sent every ~4 s
  (run2 section), and I wrote the bot without it. *Re-read what the real client
  sends repeatedly before declaring a bot "joined".*
- **Printed ~65 identical `P` rows** while checking cadence; cap output (use
  `head`/counts) when scanning a capture.

## `twi` in `MisconductSystem` (run5, Claude Haiku 5.5 work)

Goal: deduce what the `twi` field in the `MisconductSystem` directory entry
means.

### Where it lives

- `captures/run5.sqlite`, `RPC 9 DirectoryData` packets. The `MisconductSystem`
  entry is a zlib blob (`x\x9c`) inside the payload.
- Decompressed body: `<` `\x10` `MisconductSystem` `\x01` `\x03` `twi`
  `\x02` + 4-byte little-endian float + `\x00` `>`. The `\x02` is the value's
  type tag. Read the float at offset +1 after the tag (not +0): the first
  attempt was off by one byte.
- 302 `MisconductSystem` packets in run5 (ids 2654 onward).

### Findings

- `twi` is a float in game-seconds that advances with the game speed.
  Over 400 s of real time it rose from 1331.52 to about 1925 (+393.6), a slope
  of 0.983 per real second. That matches `WorldData.TimeIndex` at `gt=1`
  (see the run3 section). It is a clock, not a counter of events.
- Not yet checked: whether it stops at `gt=0` (paused) or runs faster at
  `gt=10`. Watching it while pausing would confirm the scaling.
- The name `twi` is unconfirmed. The IDA copy (`../ida-work/db/pa.i64`) was not
  opened, because idalib needs Python 3.11 here. The next step is to find the
  `MisconductSystem` save/serialize routine there and read the string literal
  for that float.

### Mistakes log (continued)

- Read the float one byte early after the type tag. Check the offset against
  the raw hex before trusting a decoded value.

## Staff Door install (run7, Claude Sonnet 5.5 work)

Capture `captures/run7.sqlite`, session 3: a `StaffDoor` placed at cell
(46, 47) at the end of the run, then built and opened by workers.

### Packet sequence (all decode)

| Packet | Event | Content |
| ------ | ----- | ------- |
| 1314 | `DirectoryData` `WorkQueue` | job 283 `InstallObject`, `ObjType='StaffDoor'`, `CellX=46, CellY=47`, `WorkTotal=7` |
| 1315 | 118 `TransactionAdded` | `object_StaffDoor: amount -100` |
| 1316 | `PlayerData` | `Job {Type='Objects', Material=41, PosX=46, PosY=47, Status=-2}` (builder job; Status 1 earlier) |
| 1638 | 13 `ObjectAdded` | `uId 8428736 as object 17, type 41` (41 = StaffDoor) |
| 1641 | `CellData` | cell (46, 47) `Mat='BuildingFrame'` |
| 1645 | `NetworkSoundSystem` | `[0, 17, 8428736, 'BeginOpen', 0]` |
| 1674 | `NetworkSoundSystem` | `[0, 17, 8428736, 'BeginClose', 0]`, `'EndClose'` |

- Object type 41 is the door's `t` in `ObjectData`; the sound cue args are
  `[0, <object index>, <uId>, <state>, 0]`.
- Cost 100 matches `Finance.v.6` (the in-game Bank Balance, confirmed by the
  user) going 26794 -> 26694 right after packet 1315.

### Parser gap found in run7

Three `ObjectData` snapshots (packets after the type 526 `ObjectAdded`, e.g.
1393) failed with `unknown field type 0x09`. The field is `has`, 8 bytes, 0.
Now decoded as int64.

### Mistakes log (continued)

- None for the door itself; the 0x09 type was simply unseen before run7.

## Object type ids across run1-7 (Claude Sonnet 5.5 work)

Every `t` seen in `ObjectData` / `ObjectAdded` across the seven captures:

| Type | Seen in | Evidence | Name |
| ---- | ------- | -------- | ---- |
| 0 | run7 | `ObjectAdded` for uId 8428662, removed again a moment later | placeholder / `None` (*guess*) |
| 1 | run7 | same uId 8428662 after the add; has `ct=41` (the StaffDoor type) | a construction site (*guess*) |
| 2 | run4, run5 | `con`, `qua` fields | material pallet (*guess*, see above) |
| 41 | run7 | `WorkQueue` job `ObjType='StaffDoor'` + `PlayerData` `Job.Material=41` | **StaffDoor** (confirmed) |
| 80 | run5 | no `o`-less extras; `p`/`o` fields only | unknown |
| 109, 124, 526 | run5, run7 | person-like fields (`eq`, `sta`, `el`, `has`, `inc.N`) | unknown, an NPC-style class |
| 139 | run4, run5, run7 | `ss`, `s` fields | delivery truck (*guess*) |
| 261 | run2 | `p`, `o` only | unknown |
| 525 | run7 | same `p` as 526 | unknown |

Type ids do not match the file order of `data/materials.txt` (inside
`main.dat`, a RAR archive; `7z x main.dat "data\*.txt"`): `StaffDoor` is the
18th `BEGIN Object` block there but has id 41, so ids are assigned at runtime
from a larger table (DLC objects, `materials_dlc.txt`, built-ins).
`Object` names in the binary (`sub_14003AEB0`, `sub_1400AC2A0`) are static
name constants, not an id table. To finish the table, either find another
`WorkQueue ObjType` + `Job.Material` pair per object (build one of each
object in a new capture), or find the runtime loader in IDA. Each new capture
that builds an object gives one more id -> name pair.

## Accepting the first grant (ad-hoc capture, Claude Sonnet 5.5 work)

Capture `captures/ad-hoc/accepting-first-grant.sqlite`, session 3 (the game
session; sessions 1-2 are name/master server). Goal: find the packets for
"accept my first grant" and add grant actions to the bot. Work in progress.

### What is on the wire (packets 332-359)

| Packet | Event | Content |
| ------ | ----- | ------- |
| 332 | 118 `TransactionAdded` | `finance_cost_grantadvance: amount +20000` |
| 333 | `DirectoryData` `Objective` | `Name='Grant_bootstraps'`, `StartingPayment=20000`, `CompletionPayment=10000`, `PaymentsMade=20000` |
| 334-340 | `DirectoryData` `Objective` | seven children, `Parent='Grant_bootstraps'`: `_holdingcell` (Room, `RequiredId='PaddedHoldingCell'`, `RequiredId2='HoldingCell'`), `_shower`, `_yard`, `_kitchen`, `_canteen` (Room, `String1='RequirementsMet'`, `Quantity=-1`), `_guard` (Objects, `Quantity=2`, `RequiredId='Guard'`), `_chef` (Objects, `Quantity=2`, `RequiredId='Cook'`) |
| 341 | 21 `ObjectiveRemoved` | `'FirstGrant', True` |
| 353, 358 | `Finance` / `VictorySystem` | `tv=20000`; `c.1 {Value=20000}` |
| 354 | `DirectoryData` `Grants` | `29 {s=1, ta=2106.29}` |

- The grant's real name is `bootstraps`; `Grant_<name>` is the parent
  objective, `Grant_<name>_<part>` its requirements. `FirstGrant` is the
  intro objective that this grant replaces, and it is removed with the
  bool `True` (the CEO letter, `ReadCeosLetter`, uses `False`).
- The 20000 advance is `StartingPayment`; `CompletionPayment` is paid at the end.
- `Grants` entries are keyed by a number (29 here, 15 in the CEO-letter
  capture) that looks like an object/grant index, not the name; `s=1` and
  `ta` (a `TimeIndex`) are unexplained.

### Open question

No `AcceptGrant` (47, `string`) or `CancelGrant` (48) packet is in this
capture: the recording is of the host, which applies the grant locally and
only publishes the results above. So the `string` argument is not yet seen
on the wire. Best guess is the grant name (`bootstraps`); to be confirmed
with a capture of a joined client accepting a grant.

## Bot game state and HUD (`captures/bot-goal.sqlite`, Claude Opus 5.5 work)

Goal: a bot that holds the game state, can send every RPC whose wire shape is
known, shows a HUD-style TUI, and can be driven by an agent. Work in progress.

### What a joining client receives (live, room `A`, region `au`)

- A plain Photon join (no game RPCs sent) gets only the host's periodic
  `DirectoryData` deltas: `World`, `ObjectData`, `Intake`, `ConstructionSystem`,
  `MisconductSystem` ~3 per second each, `EffectsSystem` now and then. No
  `SetNumSaveDataChunks`/`SaveDataChunk` (1-3) and no full snapshot.
- Sending `AuthoriseConnection("")` (5) after joining changed nothing within
  15 s: no reply, no save transfer, no kick. How a joiner gets the full save is
  being looked up in IDA (next section update).
- The host-only capture `bot-goal.sqlite` (nobody joined) has the same systems
  plus `PlayerData`, `Finance`, `NeedsDistribution`, `NetworkSoundSystem` twice
  each, and 2 `TransactionAdded`.

### Merging deltas (`src/bot/state.py`)

A snapshot holds only changed fields, under the nodes that hold them; children
are named (`ObjectData` children are the object index, `17`; `World` has
`WorldData`, `ClientData`...). Merging every snapshot of a system by node name
gives the latest value of each field seen. Replaying run5 gives balance
`Finance.v.6 = 25868` (equal to `World.WorldData.Balance`), `TimeIndex`
1353.4, the `FeedAllPrisoners` objective added then removed, and money
events. A node may repeat a field (`Bio.Traits` x4); the state keeps a list.

- Limitation: a joiner only knows what changed since it joined, so e.g. the
  balance is unknown until `Finance` next changes, and most objects are
  unknown until they move.
- Parser gap (fixed): 76 of 91 `CellData` snapshots in run5 failed with
  `expected '<' at 34`. A node with 255+ children writes its child count as
  `ff` + int32, the same escape as long strings (packet 2348:
  `ff 7a 01 00 00` = 378, matching the node's `Size=378`). Field counts get
  the same reader. All 91 parse now.
- `[i N]` children (`CellData`'s changed cells, `Convictions`) are a list sent
  whole, not stable keys, so the state replaces them instead of merging.

### Join handshake and composite types (IDA, sub-agent of Claude Opus 5.5)

Read from the decompile (`../ida-work/db/pa.i64`); scripts in
`C:\Users\mkupe\scratch\ida\`. Not yet seen on the wire.

- **Sending**: every game RPC goes through `0x1401344C0` -> `PhotonInterfaceOld`
  slot 2 (`0x14012B6D0`) as a *reliable* `RaiseEvent`. A client's commands go to
  **actor 1 only** (TargetActors `[1]`); "is host" (`0x1403C38C0`) = not
  connected, or local actor number 1. Seen for `GameSpeedChange`
  (`0x1403CA220`), `AcceptGrant` (`0x1403C8100`), `EntityUpdateRequest`
  (`0x1403CC170`), `WireDataRequested` (`0x1403CA130`). Handlers don't check
  the sender, except `AuthoriseConnection`.
- **Join** (`SaveGameSender`, built at `0x1403E49C0`, which registers ids 1-4):
  1. joiner -> actor 1: `AuthoriseConnection(password)` on a successful Photon
     join (`0x1403C3D70`); the string is the room password, may be empty.
  2. host (`0x1403C4870`): kicked name -> `KickPlayer` (6); password set and
     different -> `IncorrectPassword` (7); else the actor is queued. Joiners
     are served one at a time (tick `0x1403E4D60`).
  3. host -> joiner: `ProcessingStarted` (4), then `SendingSaveGame` (8).
     The save is a `"FullSave"` tree (`SaveGame::writeSystemSections`),
     compressed like the `DirectoryData` blobs (zlib + reversed size trailer,
     `0x14011FCB0`).
  4. host -> joiner: `SetNumSaveDataChunks(count, check)`, then
     `SaveDataChunk` (3) of at most 0x7FFF bytes. `check` mixes `count` with a
     15-bit content flag set (DLC ownership *guess*); the joiner inverts it.
  5. joiner -> host: `SaveDataChunkAck` (2) after **every** chunk; the host
     sends the next chunk only on the ack, and resets after 10 s without one.
     The joiner then joins, decompresses and loads (`0x1403E5B90`); there is
     no "done" RPC.
- **`GameSpeedChange` handler** (`0x1403CA270`): `world+136 = (float)arg`, so
  the argument looks like the multiplier, not a stop index (not confirmed).
  **`AcceptGrant`** (`0x1403C8180`) passes its string to the objectives code:
  the grant name, as guessed.
- **Composite wire values** (per-type send functions):
  `ObjectId`/`SoundObjectId` = int, int (`0x140151000`); `WorldPosition` = int,
  int (`0x1403D2870`); `Vector2` = float, float (`0x1403D42F0`); `Vector3` =
  3 floats (`0x1403C0060`); `MisconductPolicy` = int, int, raw byte, raw byte,
  int (`0x1403E67A0`); `CustomSectorNetworkData` = 12 raw bytes
  (`0x1403D2C60`); `SoundConstraint` = int type, + 2 ints if type is 1
  (`0x1403E6AB0`); `NetworkSoundId` = `0`, or `1, int, int` (`0x1403BAAF0`).
  The last two have a variable length, so the 6 sound RPCs (88-91, 95) and
  nothing else stay unbuildable. `src/protocol/rpc.py` `COMPONENTS` now holds
  these.
- **Correction to "Wire format of bool"**: the compact int reader
  (`0x140134870`) reads tag `01` as the number **1** (and `00` as 0), so a bool
  byte `01` is also a valid int 1; `decode_args` read it as 0, now fixed.
- My live `AuthoriseConnection("")` (above) was encoded `10` (empty byte
  string); the game writes an empty string as `00` (code 118). The encoder now
  writes `00`. It was also sent to "Others", not only actor 1 (host included,
  so probably not the cause).

### Mistakes log (continued)

- The IDA agent first assumed every id is registered in `0x1403C11D0`; ids
  1-4 are in the `SaveGameSender` constructor. `0x140ad7a48` is not the
  manager's vtable (`0x140ad8310` is).
- I sent `AuthoriseConnection("")` live before checking how the game writes an
  empty string, although this journal already said `00`.

### Join handshake, live (room `A`, Claude Opus 5.5)

Sent from the bot (`src/bot/savegame.py`), to actor 1 only:

- `AuthoriseConnection("")` -> host replies `IncorrectPassword` (7) at once:
  the room has a password, and the RPC reaches the host.
- `AuthoriseConnection("123")` -> `ProcessingStarted` (4), `SendingSaveGame`
  (8), `SetNumSaveDataChunks(2, 192020)`, two `SaveDataChunk`s (32770 and
  30002 bytes of `Data`: tag + size + a 0x7FFF chunk), each acked by us with
  `SaveDataChunkAck`. Joined: 62766 B, `decompress` gives a 512790 B tree
  `FullSave` with 57 sections: `Cells Objects Rooms WorkQ Regime SupplyChain
  Finance Patrols Electricity Water Research Construction Penalties Sectors
  Grants Misconduct Visitation ... Objectives ... UniformColourData
  ScriptZones CrisisSectorData FirstTimeBuiltObjectDir
  FirstTimeBuiltRoomDir DescDir`. So the IDA reading of the handshake is right.
- The root has the world fields: `NumCellsX=100, NumCellsY=80, TimeIndex,
  SecondsPlayed, ObjectId.next, Balance=48342.0, CeoLetterRead=True...`.
- `Objects` items: `{Id.i, Id.u, Type='Light', SubType, Pos.x, Pos.y, ...}`:
  the same index and uId as `ObjectData`/`ObjectAdded`, **with the type name**.
  This is the way to finish the object type id table (journal "Object type
  ids"): match `Id.i` against `ObjectData`'s `t` for the same index.
- `Finance {Balance=48415, BankLoan, StartingFunds=30000, tr.b...}`,
  `Grants {target_SolarPanels {Status='InProgress', CancelCost, ResetTime},
  ...}`, `Objectives {SelectedObjectives {FirstGrant=1, PrisonerIntake=1,
  ReadCeosLetter=1}}`, `Rooms [i n] {Id.i, Id.u, RoomType, Name}`.
- The bot now sends this right after joining (`--password` / `PA_PASSWORD`),
  keeps the tree as the `Save` system and seeds `ObjectData` (uId, `name`,
  position) from `Objects`; balance and time fall back to the save's values
  until a delta arrives.
- Every RPC the bot sends now goes to actor 1 only (`TargetActors`), like the
  game's client.

### Agent control, live (`bot serve` + `bot ctl`, Claude Opus 5.5)

`python main.py bot --region au --name-server auto --password 123 serve --room A`
joined as actor 8 next to the host `Noob` (actor 1) and loaded the save.
`bot ctl state` showed balance 48634, the grants from the save (eight
`target_*` and `Grant_bootstraps`, all `InProgress`) and objects by name
(Light 20, Prisoner 8, Workman 8, Stack 11, ...).

- **`GameSpeedChange(2)` from the bot (to actor 1) set the host's speed**:
  `World.ClientData.gt` became `2.0` within 3 s, and `TimeIndex` sped up.
  So a joined client's commands are obeyed, and the argument is the
  **multiplier** (as the IDA handler suggested), not the stop index. Set back
  with `GameSpeedChange(1)`. Wire bytes `02 02`.

## Host actions in `captures/bot-goal.sqlite` (Claude Opus 5.5 work)

The user, as the host, called vehicles (from the bot), built a power station
and cables, hired a warden, built an office and a cell, and began research.
All 27,000+ events parse (no `RpcShapeError`, no snapshot errors). The host
sends **no command RPCs for its own actions**, only their effects, so how a
*client* asks for them still comes from the binary.

### Vehicles (bot sessions 11 and 15 in the capture)

- `NewVehicleCallout(3)` x6 -> `Squads.sqd [i n] {Id.i, Id.u, Type='RiotPolice',
  ArrivalTime}` entries appear one by one, plus `TransactionAppended -100
  'object_RiotVan'`. `NewVehicleCallout(1)` x5 -> `Type='FireEngine'`. So 1 =
  FireEngine, 3 = RiotPolice. The squads left on their own by ~1259 s.
  `SquadDismissal(ObjectId)` most likely takes the `Squads` `Id` (not yet sent).
- The bot also sent 6 `IncreaseLoan` and ~44 `DecreaseLoan` (1561-1573 s).

### Object, room and material ids

| Id | Name | Evidence |
| -- | ---- | -------- |
| object 5 / 9 / 26 | Bed / Toilet / JailDoor | Job `{Type='Objects', Material=N}` then a `WorkQueue` `InstallObject ObjType=<name>` at the same cell (#70059-#70306) |
| object 14, 132, 231, 233, 241 | Chair, Warden, OfficeDesk, FilingCabinet, PowerStation | same uId in a save's `Objects.Type` and an `ObjectData`/`ObjectAdded` `t` |
| room 1 / 17 | Cell / Office | `CreateRoom(ObjectId, N)`; for the cell right after Job `{Type='Designation', Material=1}` (#68930-#69245) |
| wall material 46 | ConcreteWall | Job `{Type='flooring', Material=46, QRWallType=46}` -> `Construct` jobs `MatType='ConcreteWall'` |

Build tools seen in `PlayerData.<actor>.Job.Type`: `Foundations`, `Designation`
(room zoning; `Material` = room type), `flooring` (walls; `Material` = wall
material), `Objects` (`Material` = object type id), `-1` (no tool). `Status`
goes `1` (valid preview) -> `-2` after the click, and the `WorkQueue` jobs appear.
`Cost` is the preview price (-200 for a bed/toilet/door).

Other effects: cables -> `PowerCellModified(x, y, 1)` per cell and
`TransactionAppended -20 'object_ElectricalCable'`; the office zoning ->
`CreateRoom(..., 17)` (#39987).
Research -> `Research {N-r: progress, N-d: desired}` (ids 16, 9, 4 being
researched; names not yet known). New systems seen: `Thermometer`,
`Research`, `EventLog` (`pr.r`/`pr.re` entries: prisoner released *guess*),
`RoomData`, `SectorSystem`, `NeedProviders`, `Squads`.

### The dead prisoners

`VictorySystem.l` records 7 `Type='Died'` at ~1596 s (game time 7116) and one
`ServedTerm` (released at ~1383 s). The records have no cause. No bot RPC was
sent near the deaths except the loan spam; `FeedAllPrisoners` was re-raised all
session, so starvation is the likeliest cause (*guess*).

The user confirmed in the game's reports tab that the 7 prisoners **starved**.

## Object, material and room tables (IDA, sub-agent of Claude Opus 5.5)

The ids are not assigned from the data files: each table is a static
`std::string` array filled by an initialiser at startup, and the index is the
id. Generated into `src/protocol/game_tables.py` (from
`C:\Users\mkupe\scratch\ida\out\enums.json`):

| Table | Source | Ids |
| ----- | ------ | --- |
| objects (`ObjectData.t`, `ObjectAdded`, `Objects` job `Material`) | `0x140DFF4E0`, stride 0x20, `sub_1400AC2A0` | 0-600 |
| materials (Foundations / walls / floors job `Material`) | `sub_1400763B0` | 0-144 |
| rooms (`CreateRoom`, `Designation` job `Material`) | `sub_1400788D0` | 0-61 |
| vehicles (`NewVehicleCallout`) | `sub_140075F50` | 0-17 |
| job types (`Job.Type`, sent as the name) | `0x140DA6040`, `sub_14000ABE0` | 0-24 |
| intake types (`IntakeTypeChange`, button order, *guess* mapping) | `sub_14030DCF0` | 0-4 |

Every id seen in a capture matches: objects 5 Bed, 9 Toilet, 14 Chair, 26
JailDoor, 41 StaffDoor, 109 Prisoner, 124 TruckDriver, 132 Warden, 139
SupplyTruck, 145 Hearse, 231 OfficeDesk, 233 FilingCabinet, 241 PowerStation;
materials 46 ConcreteWall, 59 BuildingConcrete; rooms 1 Cell, 17 Office;
vehicles 1 FireEngine, 3 RiotPolice. Two object entries are filled
differently in the decompile and were added by hand: 125 SpiritualLeader,
489 Rat. Job types: 0 TopLevel, 1 Foundations, 2 WallsAndDoors, 3 flooring,
4 Designation, 5 Objects, 6 Staff, 7 Utilities, ... 14 Spawn, ... 24 Crisis.
`SpawnObject` (110) is the debug Spawn tool, not hiring.

## How a client builds (IDA + live, Claude Opus 5.5)

From the binary: a client's build tool queues jobs and sends them as
**`DirectoryData(9, "Construction", tree)`** (`sub_1403CCED0`, per frame),
not via `PlayerData` (a display mirror) or `PlanningJobChange`:

    Construction {pn=<actor>}
      Jobs {Size=N}
        [i 0] {Type='Foundations', Material=59, PosX, PosY, SizeX, SizeY, OrX, OrY, Status=1}

The host's `DirectoryData` handler (`sub_1403CDDB0` -> `sub_1403CDF70`) adds
each job with the routine its own tool uses (`sub_1404C9C00`) and re-checks it
(`sub_1404BF930`); a refused job sends the player an "OrderFailed" message.

`snapshot.encode_tree` / `compress` write the tree (byte-identical to the
host's on all 6,451 `PlayerData`/`ConstructionSystem`/`WorkQueue`/`RoomData`
trees in `bot-goal.sqlite`); `src/bot/build.py` makes the jobs.

**Live (room `A`)**:
- `foundation(10, 10, 5, 5)` -> the host's `ConstructionSystem.Jobs` got
  `{Type='Foundations', Material=59, PosX=10, PosY=10, SizeX=5, SizeY=5,
  Status=2, Cost=-1050, BatchId=14, Id=17}` (#83500); `FoundationCostSpent`
  ran to -1050 and workmen built it. The user saw it in the game.
- One batch with `room(11,11,3,3,'Cell')`, `place('Bed',11,11)`,
  `place('Toilet',13,11)` and `place('JailDoor',12,14)`, sent while the
  foundation was still being built: only the **JailDoor** was taken (a
  `WorkQueue` `InstallObject ObjType='JailDoor'` at (12,14), then a JailDoor
  object). No bed or toilet job and no `CreateRoom`. Not yet known whether
  they were refused because the floor wasn't finished, or whether zoning
  (`Designation`) uses another path.

### The bot's cell, intake and alerts (live, Claude Opus 5.5)

- Retried once the foundation was finished: `room(11,11,3,3,'Cell')`,
  `place('Bed',11,11)`, `place('Toilet',13,11)` -> `InstallObject` Bed and
  Toilet jobs, then `CreateRoom(uId 8459050, index 4, 1)` (a Cell); Bed (#62)
  and Toilet (#63) objects installed. The first try failed only because the
  floor wasn't built yet.
- Intake: the save had `Intake {IntakeType=0}` (off). `IntakeTypeChange(1)`
  -> the host's `Intake {t=1}` (FillCapacity; IDA button order confirmed for 1).
  At the next 08:00 (game time; `TimeIndex` is minutes, 1440 per day) two
  Prisoners (type 109) arrived (#93565). A fresh save showed the bot's cell
  `Rooms [i 4] {RoomType='Cell', Entity.i=65, Entity.u=8460687, RoomError=4}`:
  **prisoner #65 assigned to the bot-built cell.** `Entity` on a room is its
  assigned person (the office's is the warden).
- `ObjectData` `ci` stays -1 for new prisoners (not the cell link).
- Hiring is a `Staff` job (`{Type='Staff', Material=132}` for a Warden, host
  `PlayerData`). Cables and pipes are `Objects` jobs drawn as a line with
  `SizeX`/`SizeY` (`Material=243` ElectricalCable; `PipeLarge` 248, `PipeSmall`
  249, `WaterPumpStation` 245, all accepted from the bot as `InstallObject`).
- **Alerts**: the warden's "The general quality of our cells is too low." came
  as a `StaffAlert` snapshot `sa [i 0] {tts='d11_staffalert_summary_PRISONERS03',
  aa=132}` (`aa` = the staff object type); advisor speech as
  `NewSpeechAdded(1, 'help_warning_prisonerreleased')`. The text is in the
  game's `data/language/*.txt` (key, whitespace, text) inside `main.dat`;
  `src/protocol/game_text.py` is generated from it.
- **Room errors** (IDA `sub_1401EB850`, switch on the room's int at +196 =
  save `RoomError` / `RoomData.Updates.<room>.re`): 1 nokitchen, 2
  noprisoners, 3 nocanteen_kitchen, 4 nocanteen_cells, 5 deathrow_sharedcell,
  6 nonursery, 7 laundryoverloaded (`roomerror_<name>`). Both cells show 4.
- **No power**: the flashing icon is not sent. Electrical objects
  (`Properties Electrical` in `materials.txt`, incl. `WaterPumpStation`) have
  `Powered=True` in the save when powered; the new pump had none. Computed
  by the bot as `problems` from a fresh save (a repeated
  `AuthoriseConnection` makes the host send a new save at any time).
- **Research ids** (IDA, static array `0x140DF4A20`, `sub_140096B10`):
  0 None, 1 Warden, 2 Maintainance, 3 Security, 4 Legal, 5 MentalHealth,
  6 Finance, 7 Cctv, 8 RemoteAccess, 9 Health, 10 Cleaning, 11
  GroundsKeeping, 12 Deployment, 13 Patrols, 14 Dogs, 15 PrisonLabour, 16
  Education, ... 34 LegalDefense. "Bureaucracy" is the office, not a research
  id; the user's research started 16/9/4 = Education, Health, Legal.

### Mistakes log (continued)

- Assumed language lines are `key<TAB>text`; many use spaces, so the first
  text table missed every `roomerror_*` key.
- First guessed `STAFF` names by hand; replaced by the binary's tables.

### Haiku agent playing via `bot ctl` (Claude Opus 5.5)

- **Attempt 1** (Haiku 5.5, guide `src/bot/PLAYING.md`): `ctl build foundation
  24 10 5 5` was accepted and the floor (9 `ConcreteFloor`) built, but the 16
  edge cells stayed `BuildingFrame` and the `Foundations` job stayed listed
  (`Hidden=True`, `Counter` cycling) for ~6000 game minutes. The agent took
  that as "not finished" and gave up.
- **Why**: my first foundation's frame turned into `ConcreteWall` all at once
  (cell (10,10) at 2212 s, no wall job), 3 s after the bot placed a JailDoor
  in it. The second never got a door. Placing a JailDoor at (26,14) on the
  Haiku foundation turned its frame into walls within a minute. So **a
  foundation's walls go up only once it has a door** (observed twice). Wall
  jobs (`flooring` ConcreteWall) over a `BuildingFrame` are refused silently.
- New `ctl area X Y W H` (cells from the save's `Cells "x y" {Mat, Ind,
  Room.i}` and live `CellData [i n] {x, y, Mat}`) shows the build as a grid of
  letters; the guide now says door first, and how to check each step.
- Gotcha for agents: Git Bash rewrites `/Construction`-like arguments into
  Windows paths; use PowerShell.
- **Attempt 2** (Haiku 5.5, fixed guide, ~25 `ctl` calls, no help): foundation
  at (24,17) -> JailDoor at (26,21) -> walls up -> `room 25 18 3 3 Cell`, Bed,
  Toilet -> `room created: #5 Cell` -> next 08:00 intake brought prisoner #75
  -> `ctl refresh`: **Cell room 5, occupant 75**. Verified by me on a fresh
  save (`ctl area 24 17 5 5`: `WWWWW / WFFFW x3 / WWFWW`, rooms [5]). Goal of
  "an agent builds a foundation and a cell and gets a prisoner into it" met.
- Its notes: say how much game time a `ctl wait 30` covers (~300 game
  minutes at 10x); the door cell reads `F` in `ctl area`.

## Haiku completes grants (`captures/bot-goal-2.sqlite`, Claude Sonnet 5.5 work)

Game `MKS` (password `123`, host `RealHost`), bot joined with `-o captures/bot-goal-2.sqlite`.
Grants in the save: `Grant_bootstraps` plus eight `target_*` objectives, all
`InProgress`. Only `target_PowerStation` has a progress task (`TimePassedGreen`,
quantity 5); `Grant_bootstraps` shows no requirements in the save, so they come
from the capture in "Accepting the first grant".

- **Round 1 (Haiku 5.5, ~55 `ctl` calls)** built five 3x3 rooms (HoldingCell,
  Shower, Yard, Kitchen, Canteen; each foundation + JailDoor + `build room`),
  and stopped on the staff: nothing in the bot could hire.
- **Hiring** is a `Construction` job `{Type='Staff', Material=<staff object
  type>}` (Guard 105, Cook 113, Warden 132). `ctl hire Guard 2` sends it and two
  `Guard` objects appeared within seconds (balance fell as wages/hire cost).
- **The user's note: the rooms did not meet the minimum requirements.** They
  are in the game's own `data/materials.txt` (`BEGIN Room`, in `main.dat`):
  `MinimumSize`, `Enclosed`, `Indoor`, `Secure` and required objects with
  alternatives. HoldingCell 5x5 + Toilet + Bench; Yard 5x5 + Secure; Kitchen
  Cooker + Fridge + Sink; Canteen ServingTable + Table + Bench/DiningChair;
  Shower ShowerHead; Cell 2x3 + Bed + Toilet. Generated into
  `src/protocol/room_rules.py`; `state.problems` now says e.g. `HoldingCell #6:
  lacks size 3x3, needs 5x5, Toilet, Bench`; `ctl rules [Room]` prints them.
  Round 1's rooms: HoldingCell and Yard too small, Kitchen lacked Fridge and
  Sink, Canteen lacked a ServingTable. (Round 1's Fridge/Sink "were accepted
  but never appeared": the rooms were too small or unpowered; see round 2.)

### Short snapshot keys (IDA, offset pairing)

`ctl state` showed keys like `st`, `ci`, `ts`, `twi` unexplained. The game
registers each synced member twice in its constructor: under the long save
name and under the short network key, both bound to the same offset in the
object (`sub_1407D1E10` WorldObject: `SubType` at +68 and `st` at +68, `Walls`
+92 / `wa`, `Damage` +104 / `da`, `Dryness` +560 / `dry`; `sub_14052F7B0`
Person: `Carrying` +792 / `ci`, `Energy` +812 / `el`, `RestState` +816 / `rs`,
`Dest` +748 / `d`, ...). Pairing them by offset (script kept outside the repo)
gives `src/protocol/net_keys.py`; `ctl state` now prints `SubType (st)` (use
`--raw` for the short key), and `ctl keys [System]` lists them.
- Corrects an earlier note: `ci` is **Carrying** (the object a person carries),
  not a cell link; `uId` is the object's `Id`; `sl0`-`sl19` are `Slot0`-`19`.
- Keys that mean one thing per class (`ObjectData` mixes them): `ct` Contents
  (container) / Target (needs), `op` Opened / Open (door), `s` State (vehicle)
  / Shakedown, `ts` TargetSector / TunnelSearch.
- Still unknown (registered without a save name): `a`, `ttt`, `inst`, `cr`,
  `la`, `esr`, `sc`, `sj`, `si`, `tun`, `tdc`, `pil`, `pis`, `prs`, `o`, `p`,
  `v`; marked `?` in the table.

### Demolishing a building (your bulldoze in `bot-goal-2`, packets 51148-51602)

The host user bulldozed, demolished walls and cleared the indoor area of the old
foundations. Each is a plain **`flooring`-tool job**; `Material` is one of the
game's demolition materials (already in `MATERIALS`):

| Packet | Job (host `PlayerData` / `ConstructionSystem`) | `WorkQueue` `MatType` |
| ------ | ---------------------------------------------- | --------------------- |
| 51148, 51239 | `{Type='flooring', Material=2, PosX=40, PosY=52, SizeX=5, SizeY=5}` | `Demolish` (`Type='Construct'`, `Dismantle=0`) |
| 51282, 51448 | `Material=3`, same area | `DemolishWalls` |
| 51602 | `Material=5` | `ClearIndoorArea` |

2 Demolish, 3 DemolishWalls, 4 RemoveTunnels, 5 ClearIndoorArea, 6 SellFlooring,
7 SellMaterial. The bot sends these as client jobs with `ctl demolish X Y W H
[-n DemolishWalls]` (`build.demolish`); untested live until Haiku's round ends.
The earlier guess that bulldozing was a separate job type or `Dismantle` flag
was wrong: `Dismantle` is a `WorkQueue` field and stays 0 here.

### Power reach (from the host user, in-game observation)

- Cables are built by the bot's `Objects` line jobs, but a consumer only gets
  power if a cable **touches** it; only `Light`s also pick up power from a cable
  a few cells away ("induction").
- **Walls cut that reach, doors do not**: a cable down a hallway can light a
  room through its door; a room with no door on the cable's side needs its own
  cable inside. (Explains Haiku round 2's "no power" on the new rooms' lights.)
- Bot: `ctl wire X1 Y1 X2 Y2` (cable along x then y); `problems` says "a cable
  must touch it" for unpowered non-lights.
- **Overload** (host user): too many consumers cut *all* power and the
  PowerStation reads "Overloaded, remove electrical items or add Capacitors".
  In the save the station object has `Capacity=50` and `Overloaded=1` (seen on
  PowerStation #52 at 60.5,26.5 in `bot-goal-2`); `problems` reports it. A second
  PowerStation needs fully separate cables: crossing power lines short-circuit.

### Bureaucracy tab (Haiku 5.5 attempt 1, `bot-goal-2`)

- Tab = Research (`BeginResearch(int)` 36, `ToggleResearchDesired(int)` 37; ids
  as in "Research ids" above), Misconduct policy (`PolicyChange` 61: `int,
  MisconductPolicy, int`; rows Punishment, Quantity, SearchPrisoner, SearchCell,
  CategoryChange), Reform (`StartReformProgram` 82 / `StopReformProgram` 83;
  the save has `NextProgramId=0`, no programs), `PrivilegePolicyChange` 62,
  `MealPolicyChange` 63, `FarmingPolicy` 102. Save `/Research` has 43 entries by
  name (35 enum ids plus GuardTowers, ForestryLabour, Orderly, Farming,
  RecyclingIncentive, NonLethalSniper, StaffVetting, CCTVImprovement).
- **Mistake: the agent started 24 researches in one batch without looking at
  the balance.** The cost is charged up front on `BeginResearch` (Cctv 2000,
  TazersForEveryone 5000, LowerTaxes2 / LegalPrep / LegalDefense 50000 each...
  about 219,000 in all) and **the balance went negative (-105,190)**; the game
  allows it. `ToggleResearchDesired` off stops progress and refunds nothing.
  Guide now says: check `balance` and the price first, research one at a time.
- Read-back: `ctl state Save` is stale until `ctl refresh`; right after a start
  `Progress` is `9.99999974e-05` (a 0.0001 seed, not real progress).
- Unexplained: `CategoryChange` values None/Up/SetMax, `Grants.CancelCost` and
  `ResetTime` (0 here), `PolicyChange` arg 2 and `MealPolicyChange` ints.

### Haiku round 3: wires, demolish, power station (`bot-goal-2`)

- **Demolish works from the bot**: `ctl demolish 48 52 5 5` (Material 2, default)
  took the whole 5x5 foundation (floor and walls) to nothing in about 20 s and
  the room was removed; `DemolishWalls` / `ClearIndoorArea` were then sent on an
  empty area, so their individual effect on a standing building is untested.
- **Wires**: `ctl wire` bridged the cooker/fridge cable piece (x41..45, y63..64)
  and Cooker #96's piece (x65..67, y53) into the main 237-cell network with one
  cell each (41,62 and 65,52): one 252-cell component. Afterwards the
  PowerStation was `on=false`, lights that had been powered went dark: this is
  the overload described above (merging grids put every consumer on one station
  of Capacity 50). The "cable must touch it" hint is wrong for that case.
- Fix to try: a Capacitor, or a second PowerStation on cables that never touch
  the first, instead of bridging. `ElectricalSwitch(uId, true)` did nothing
  while overloaded.
- Open: `target_PowerStation` has the only progress task (`TimePassedGreen` 5,
  deadline 14400): it needs a running station; no data for the other targets in
  the save.

### Why every research is stuck (host user; `data/research.txt`)

Each research has `Requires` (another research), `Cost` (negative, charged up
front) and `Admin`: the research whose staff entity must be **hired and in his
office** (the game shows "REQUIRED: Chief|Accountant|..."). The staff entity is
that research's `Sprite`: Warden -> Warden (132), Maintainance -> Foreman (134),
Security -> Chief (133), Legal -> Lawyer (138), MentalHealth -> Psychologist
(135), Finance -> Accountant (137). Counts of `Admin`: Security 14, Warden 10,
Finance 6, Legal 6, Maintainance 5. So Haiku's 23 paid researches never ran:
no Chief/Lawyer/Accountant/Foreman existed. `src/protocol/research_rules.py`
(generated from the game files), `ctl research`; hire with `ctl hire <role>`
(`Staff` job; the roles are in the object table).
- Money cheat attempt on the dummy game: `IncreaseLoan` (49) x3 and `AcceptGrant`
  on an in-progress / completed grant changed nothing (balance moved only by
  cashflow). No RPC credits money; a client cannot send `TransactionAdded`.

### Money cheat attempts (dummy game, client -> host)

- `TransactionAdded(1000000, 'finance_cost_grantadvance'|'finance_cost_cashflow',
  0, '')` sent to the host actor: the **host's transaction list shows the
  amount** (user), but the bank balance does not change.
- The balance is in the live state in three places: `Finance.v.6` (bank
  balance; `Finance.tr.b` is the balance at the last transaction, `tr.tI` / `tr.tO`
  total in / out), the save's `Finance.Balance`, and `World/WorldData.Balance`
  (float).
- `DirectoryData` sent from the bot with `Finance {v.6}`, `Finance {tr.b, v.6}`,
  `Finance {Balance}` (float) and `World/WorldData {Balance}` (float): all
  ignored by the host (the next fresh state shows only cashflow). So the host
  does not take a client's Finance / World directory data; `IncreaseLoan` (49)
  and `AcceptGrant` on an open grant also did nothing.
- Open: a capture of whatever the user does on the host (or another client)
  to change the balance would settle it.
- **Imitating the server**: not possible and not needed. Photon stamps the
  sender actor on forwarded events, so a client cannot appear as the host. And
  the host's `DirectoryData` receiver (`sub_1403CDDB0`) only takes two system
  names from others: `Construction` (-> `sub_1403CDF70`, jobs + `pn`) and
  `PlayerData` (a display mirror). `Finance` / `World` are never read from a
  client, which is why the injected balance did nothing.
- Round 4 (Haiku): a Capacitor placed at 42,27 and 40,27 never appeared; builds
  are probably dropped while the balance is negative (guess, unverified).
  `ctl demolish` on a cable cell queues a `flooring` job and leaves the cable;
  no cable-removal job known.
- Income idea: `finance_cost_prisonerintake` pays +800 per arriving prisoner
  (host-side, seen at packet 29058). `RemovePrisoner(prisoner)` takes
  `uId,index` (`ctl send RemovePrisoner 8562964,27`).
- **Spoofing the sender on our own server** (user idea): the local Photon server
  (`src/server/game_server.py`) stamps `ActorNr` on every forwarded event, so
  with `PA_SPOOF_HOST_CODES=118` events with those RPC codes from any player
  leave the server as if sent by the master client (the host). Untested live:
  it needs the host client and the bot both connected to the *local* server
  (hosts redirect of `ns.exitgames.com` to this machine), not the real cloud
  where MKS runs. Theory to test: the host's `TransactionAdded` handler (118)
  only moves the balance when it comes from the server/host actor, which would
  explain why a client's copy only showed up in the transaction list.
- **Construction is refused at a negative balance** (strong evidence, balance
  about -111,800): a 4x4 `foundation` on empty ground at (5,70), a Light and a
  Capacitor inside a finished room, and a Toilet were all accepted by the bot
  but never reached the host's `ConstructionSystem` (`Jobs Size=0`, no error
  event). Before the research spree the same calls worked. `SellFlooring` (material
  6) over a finished 7x6 room did nothing visible either. So: **never let the
  balance go below 0**; it blocks every grant that needs building (the power
  targets, `FeedAllPrisoners`).

### Game speed past 10x (MKS, bot sends `GameSpeedChange(n)`)

Measured game minutes per real second (`TimeIndex`): n=3 -> 3.2, n=4 -> 4.3,
n=10 -> 10.5; n=11, 20, 50, 100, 127, -1 -> 9.6-9.7, 1,000,000 -> 7.8. The host
accepts any int as the multiplier but clamps it at 10x (the extra scatter is
the host's frame rate), so 10 is the ceiling; there is no way to go faster
from a client. `World.ClientData` shows `gt=2.0` (a unit unknown here) while the
speed is 10.

### More short keys (offset pairing, `SectorSystem`, electrical, `Thermometer`)

Same method as "Short snapshot keys" (constructor registers the long save name
and the short net key on one member offset):
- **SectorSystem** (`Sectors/<id>/<list>`, lists of ids): `s` Stations, `ds`
  DogStations, `as` ArmedGuardStations, `os` OrderlyStations, `cs`
  CookStations, `docs` DoctorStations, `js` JanitorStations, `gs`
  GardenerStations, `fs` FarmerStations, `j` Jobs, `cr` ContainedRooms, `l`
  Targets. The order is the save's `Sectors/<n>` order, and values match
  (sector 46: `cr`=[8], `l`=[33]; sector 66: `l`=[75], equal to the save's
  `Targets`). Children are labelled too now: `/ContainedRooms (cr)`.
- **Electrical** objects (`0x14052C720`, `0x140694BE0`): `sw` Switch (+568),
  `pow` Powered, `on` On, `ep` ExternalPower, `mo` Moved, `dem` Demand (+608),
  `cap` Capacity (+612), `pt` Powertype. **Crates/mail**: `qua` Quantity, `mt`
  MailType, `con` Contents.
- **Thermometer** (`0x140739A80`): `t` Temperature, `roc` RateOfChange, `sm`
  StaffMorale, `sroc` StaffMoraleRateOfChange, `ru` RiotUnderway.
- **VictorySystem** (`0x14074F160`): `fc` FailureCondition, `rdt`
  RecentDeathTimer, `ret` RecentEscapeTimer, `sp` StaffPayBeforeDemand; `npg`,
  `rdp`, `rep`, `ft` have no save name.
- Still unnamed in `ctl state`: `Finance.v.<n>` / `tr.*` (6 = bank balance; `tr.b` the
  balance at the last transaction, `tr.tI` / `tr.tO` total in / out, `tv` a
  target value), `Intake` (`i`, `cat`), `Contraband` (`d0`, `s1`...),
  `NeedsDistribution` (`c`/`h`/`l`/`m` + need id), `Visitation.w`, `WorkQueue`
  (`i` items, `ri`), `EffectsSystem`, `EventLog`, `VictorySystem` (`c`, `l`).

### Switching a PowerStation (user switched it on in `MKS`; `bot-goal-3`, `-bot`)

- The host's own switch-on is not an RPC on the wire: in the proxy capture
  (`bot-goal-3.sqlite`, packet 26201) it is only an `ObjectData` change on the
  station, `52 {sw=True, on=True}` (`sw` Switch, `on` On), and in the bot's
  capture (packet 15499) the same, followed at 15520 by `pow=True, on=True` on
  every consumer (Lights 31-54, Cooker 70/96, Fridge 75...) and the station's
  `dem=68.0` (demand). Before it the station had been `sw=False, on=False`
  (proxy packet 11212).
- **Client side: `ElectricalSwitch(34, int, bool)` takes the object *index*,
  not the uId** (an earlier try with the uId 8444868 did nothing). Sent from
  the bot: `ctl send ElectricalSwitch 52 false` -> station 52 `sw=False, on=False,
  dem=0`; `... 52 true` -> `sw=True, on=True, dem=68`. (`bot-goal-3-bot`.)
- Haiku's round 5 had meanwhile built four Capacitors (type 242; objects 93,
  37, 80, 88): each raised the station's `cap` 100 -> 150 -> 200 -> 250 in
  `ObjectData` (packets 4744-4997), so the "overloaded" state is cleared by
  capacity, and the station only needed to be switched on.
- Not the station's fault: the bot said "dead end" because it looked for a
  switch object (`PowerSwitch`, 244) and passed a uId.

### Haiku water + power round (`bot-goal-3-bot`)

- **Overload cleared by capacity**: two more Capacitors (`build place 63 26` and
  `56 27 -n Capacitor`) took `Main_Power_Station` (object 52, uId 8444868) to
  `Capacity 250` against `Demand 65`; `problems` then lists no overload.
- Objects 25 and 82 are **`Box` crates with `Contents='PowerStation'`**, i.e.
  ordered stations waiting as deliveries, not stations (Haiku named them by
  mistake: `ctl name set X 25` pointed at a Box). Items placed by the bot arrive
  by supply truck as a crate first; the bot's `problems` once counted them as
  stations while the live `ObjectData` still had the type.
- **Water**: pump `WaterPumpStation` object 59 at 19.5,12.5 (uId 8463110),
  powered. `PipeLarge` main line `ctl wire 19 13 19 69` then `19 69 -> 63 69`,
  `PipeSmall` branches to each toilet / shower head / sink; no water problem
  remained for rooms #11-#15. Pipes and cables are separate layers: they may
  share cells.
- **Power to the south rooms**: a cable trunk down x=23, a row at y=70 with
  branches up each door column (x=23, 33, 53, 63). A building at x 17-21, y 39-46
  blocked the straight route.
- `ctl demolish` bulldoze + `-n DemolishWalls` + `-n ClearIndoorArea` removed
  the old Kitchen #9 and Canteen #10 (64,52 and 72,52, 5x5).
- Left: "There are no canteens accessible by this cell" for Cell #3 and
  HoldingCell #11 (the canteen has an empty `Connected` in the save; guess: no
  indoor route from the cells to the canteen), and Lights #61, #112 behind
  walls.

### Correction: the Box crates are the user's dismantled stations (logs)

Objects 25 and 82 were not deliveries. The user dismantled two PowerStations
in-game: in `bot-goal-3-bot2.sqlite` event 14 `ObjectRemoved` of the station
(25: uId 8592998, packet 2841; 82: uId 8616049, packet 2929) is followed at once
by event 13 `ObjectAdded` of a **`Box` (type 1)** reusing the same index (25 ->
uId 8620408 at 2927; 82 -> uId 8620424 at 2963), with `Contents='PowerStation'`
in the save. An index is reused after a removal, so a name must be checked
against the uId (`ctl name list` shows `current`). Earlier in the first
session the same indices held other objects (types 139, 161, 140, 83, 2).

### The `target_*` grants are the Going Green DLC's "Green Energy Goals"

Text from the game's `data/language/d11.txt` (`objective_target_<name>_task`):

| Objective | Goal (task) | Reward |
| --------- | ----------- | ------ |
| `target_SolarPanels` (1) | purchase 3 solar panels | unlocks the Wind Turbine |
| `target_WindTurbine` (2) | purchase 3 wind turbines | unlocks the Solar/Wind Hybrid |
| `target_ExportPower1` (3) | export 1000 units of power | export cap 1000 |
| `target_ExportPower2` (4) | export 2500 units | cap 2500 |
| `target_ExportPower3` (5) | export 5000 units | cap 5000 |
| `target_PassReform` (6) | 25 inmates pass the **Solar Panel Development** program | bonus to its reform rate |
| `target_GreenEnergySource` (7) | purchase 10 solar panels, 10 wind turbines, 10 hybrids | weather effects halved / doubled |
| `target_PowerStation` (8) | **do not use a Power Station for 10 in-game days** (with prisoners present); save `TimePassedGreen`, deadline 14400 = 10 days of minutes | one of each green source delivered free |
| `target_ChargeBattery` (9) | fully charge 100 batteries | green output x2 |

So the station Haiku was asked to keep running is the opposite of what goal 8
needs: **switch it off** (`ctl send ElectricalSwitch Main_Power_Station off`) once
solar / wind / hybrid supply the prison, and keep it off for 10 days. Exporting
power uses a `PowerExportMeter` (object 390) and the buildtoolbar text says a
PowerStation "can also be connected to a Transformer to export power". The
older `Grant_GreenMachine` (solar / wind / hybrid, one each) is a separate grant.

### Bureaucracy tab, attempt 2 (Haiku 5.5, `bot-goal-3-bot`)

- Staff hired with `ctl hire` (Chief, Foreman, Accountant, Lawyer; the Warden
  already sat in Office #2) and each placed in an Office room with an
  OfficeDesk, Chair and FilingCabinet: rooms 6 (Accountant), 7 (Lawyer), 8
  (Chief), 16 (Foreman); StaffDoor on the bottom edge. One occupant per Office
  room (`Entity` of the room). Idle staff read `ca=0`, `ji=-1` (Action and JobId
  of the person, see "Short snapshot keys"), `Dest` next to the desk.
- Research moves only at speed 10 in the agent's tests, and only after the
  matching staff member sits in an office. Of the 23 researches stacked in the
  first attempt (stalled at `Progress 0.0001` with no staff), sixteen finished
  once staff existed: Cctv, RemoteAccess, Cleaning, GroundsKeeping, Patrols,
  PrisonLabour, LandExpansion, Armoury, BankLoans, ExtraGrant, Deployment,
  Contraband, Dogs, BodyArmour, Tazers (1.0) and LowerTaxes1 (0.97 at the
  last read); Deathrow 0.38 running; RemoveMinCellSize 0.0001 (both need the
  Lawyer, who works one at a time). Not started: TazersForEveryone,
  LowerTaxes2, PermanentPunishment, ReduceExecutionLiability, LegalDefense.
- The agent could not start a research with `BeginResearch` (Desired stayed
  false, no charge) and used `ToggleResearchDesired` off/on instead. Not
  understood: the first attempt's `BeginResearch` did charge money. Possibly
  `BeginResearch` is refused for a research already `Desired`.
- Policies were left at the save's values (Quantity 3, Variety 2, ParoleCutoff
  40, VisitationHours 3). Reform: `StartReformProgram 0 true` creates program 0
  with `Error: NoRegimeTime` (no schedule slot); a program needs
  `ScheduleProgram <program> <day> <hour> <room>` and a room (classroom /
  workshop); stopped again with `StopReformProgram 0`. The `Solar Panel
  Development` program is what `target_PassReform` counts.
- The new offices' lights had no power (grid damage around x 12-65, y 12-64
  at that time).

### Green farm and the prison grid (Haiku green round + diagnosis, `bot-goal-3-bot*`)

- **Footprints** (game data `materials*.txt`): SolarPanels 3x2, WindTurbine 2x3,
  SolarWindHybrid 3x3 (the agents assumed 2x2), PowerStation 3x3, Transformer 2x2,
  PowerExportMeter 2x2 (`Wired`), Battery 1x1, Capacitor 1x1, PracticeSolarPanel
  1x2 (4 slots). Generators are `BlockedBy Cable`: cables run along their edges,
  never through them. Positions in the save are centres.
- **Generators have a `Switch`**: solar, wind and hybrid objects have
  `Switch` / `On` / `Capacity` (75, 75, 250) / `Powertype 1` like the PowerStation
  (`Powertype 0`?). Eighteen of them were `Switch=False` and had to be switched
  on one by one (`ctl send ElectricalSwitch <index> true`).
- **The farm was not wired to the prison** (cable flood fill over `Save
  Electricity`, 718 cable cells): the PowerStation and every consumer were in one
  network; the farm sat in three separate ones (163 + 61 + 37 cells). After the
  two missing links (`build line 65 25 1 1` and `72 33 1 1`) everything is one
  621-cell network with 10 hybrids, 6 solar, 5 wind, 5 Capacitors and the station.
- **Result: the whole prison went dark** (31 problems, only the 9 lights next to
  the farm powered), with the station on or off, at night and at 16:00 game
  time. Every generator in that merged network reads `Overloaded=3` (and no
  `On`), while the 9 generators in a farm island of their own (5 wind, 4 solar)
  read `On=True` and nothing else. Reading: `Overloaded` 1 = demand over
  capacity (seen with Capacity 50, Demand 65); **3 = generators of different
  kinds (PowerStation + green sources) on one network = the short circuit the user
  described**. Unproven; consistent with `target_PowerStation` needing no
  PowerStation at all.
- **To finish goal 8** the PowerStation must be removed from that network
  (dismantled). The bot cannot do it: `ctl demolish` (bulldoze) over the station's
  3x3 footprint left it standing, there is no dismantle RPC, and cables cannot be
  removed. The user's in-game dismantle shows up on the host as a **`WorkQueue`
  job** `Type='DismantleObject'`, `PlayerIssued=False`, `ObjAssigned.i/u` = the
  object, `ObjType='PowerStation'`, `WorkTotal=40` (proxy packets 53702, 53748,
  then `ObjectRemoved` 53861, 53945). Needs a client-side request that the host
  turns into that job; not found. (A `Construction` job of type
  `DismantleObject` is untested.)
- `problems` now reports `Overloaded` on any generator type, with value 1 as
  "overloaded" and any other value with the shared-network hint.

### Pause point: state when the game was reset (MKS, `bot-goal-3-bot3`)

- **Goal 8 clock does run with the station off.** `ctl send ElectricalSwitch
  Main_Power_Station off` (at game minute about 127410) made the grant's progress
  node `Save Grants/target_PowerStation/Progress/target_PowerStation_task`
  (`Type=TimePassedGreen`, `Quantity=5`, `Deadline=14400`) report `GreenDeadline
  = 141810.14` = switch-off time + 14400: the grant completes at that game
  minute (about 24 real minutes at 10x) if the station is never switched on
  again. `Save Objectives.TimePassedGEG=14400` is the limit, not the progress.
  The prison need not be powered for it to count (it was dark).
- **Dismantling / removing** (user capture 53615-53702: `DismantleObject` host work
  jobs, `PlayerIssued=False`, created by the host's own UI): no client route found.
  Tried `Construction` jobs of Type `DismantleObject`, `Dismantle`, `Objects`,
  `Demolish`, `Utilities` (material 243, 0, -1) and `DismantleUtility`, and
  `flooring` Material 2: none removed the station or the cable at (65,25).
  A Haiku agent reports plain `ctl demolish X Y W H` (default Material 2) removed
  *cable cells* for it (not `DemolishWalls`); unverified by me, and bulldozing
  does not remove objects (Lights at 88.5,20.5 and 94.5,30.5, the PowerStation).
- **Battery and Transformer need a building**: `IndoorOutdoor 0` in the game
  data, and 77 Batteries placed along an outdoor cable trunk (y=4 and y=6,
  x=60..98) were never built; Solar/Wind/Hybrid are outdoor (1), PowerExportMeter
  Either, PracticeSolarPanel 2. A battery hall (foundation 89,14 11x16 and 89,33
  11x17 with a JailDoor each, interior cable rows and a spine at x=90) was
  started; not finished.
- **Reform ids** (Haiku): `StartReformProgram N` takes a *program type* index; type
  12 is FirstAidTraining; 'SolarPanelDevelopment' is probably 10 (IDA string
  table order, unconfirmed). A scheduled program with no teacher shows
  `Error NoTeachers`; one with no regime slot `NoRegimeTime`. Reform instances
  cannot be deleted by the bot (duplicates remain). Workshop built at
  71..75,53..57 (room 9) with WorkshopSaw, WorkshopPress, SmallTable (`Table`
  refused) and 2 of the 5 PracticeSolarPanels.
- **Status at the reset**: Grant_bootstraps, target_SolarPanels and
  target_WindTurbine Completed; target_GreenEnergySource counts 10/10/10;
  target_PowerStation clock started; Export, Battery and PassReform not done.
  Bureaucracy: staff hired and seated, sixteen researches done.

### A real client builds a foundation (as seen by the bot in MKS2, `captures/mks2-bot.sqlite`)

The host mirrors each player's pending tool use in `PlayerData` (`Job {...}`
with `Status=1` while the area is valid, `Status=-2` when refused). Dragging a
foundation over several frames: `SizeX/SizeY` 1x1 -> 5x7 -> 10x10 -> 14x10 at
(58,27), with `Cost` -60, -1350, -2800, -3600 (negative = price) and `Speed`
60 -> 100 -> 140 (grows with the area; 60 for a single cell). On release the
host adds it to `ConstructionSystem` as `Status=2`, `Counter`/`Counter2`
(cells left), `BatchId=0`, `Id=0`, `FoundationCostSpent`. Objects:
`Job {Type='Objects', Material=424, OrY=1, Cost=-200, Speed=60}` (one preview
per placed cell). The preview fields `Cost`, `Speed`, `QRWallType=46` are
host-computed; the bot's own `Construction` jobs (which it sends) carry only
Type, Material, Pos, Size, Or, Status=1.

### A real client hires a warden and builds an office (MKS2, `mks2-bot.sqlite`)

- **Hire** (packets 4326-4361): the host mirrors the client's tool as
  `PlayerData/2 {jp.x, jp.y, js.x=-1, js.y=-1}` + `Job {Type='Staff', Material=132,
  PosX, PosY, Status=1, Cost=-1000, Speed=60}`. `PlayerData/<n>` is the player's
  **actor number** (2 = RealClient); `jp` = the cell under the tool, `js` = where a
  drag started (-1 = none), `p` = cursor in world coordinates. Unlike the bot's
  `Staff` job (PosX/PosY 0,0, which also works) the client sends the **cell where
  the new staff member appears**; price 1000 for a Warden. Then `ObjectAdded`
  (271628, 17) type 132 at 4369.
- **Office**: `Designation` Material 17 (Office) -> `CreateRoom` (271714, 2)
  type 17 at 4667; objects `OfficeDesk` (231, `Status=-2` first when refused
  at (71,35), then placed), `FilingCabinet` 233 (-30 each), id 214 etc.
  ObjectAdded OfficeDesk (271997, 54) at 5265, FilingCabinet (272069, 55) at 5428.
- The agent's own jobs in this capture, for comparison: `Construction` jobs
  `Objects Material=387` (SolarPanels) at (10,10) became `ConstructionSystem`
  `Status=16, Cost=-2000, BatchId=2`; `Status=16` is the state of an accepted
  object job waiting for its delivery (the real client's reads 1 -> 2 for
  foundations, 16 for objects).

### The CEO's "call" (MKS2, `mks2-bot.sqlite` packet 7372)

The call the user saw is an advisor speech: `NewSpeechAdded(1, 'help_warning_prisonerreleased')`
(a prisoner had been released). The text (`d11.txt`): "Reform Programs are key to
prisoners successfully reintegrating into society... Reformed prisoners bring an
additional cash reward; those who reoffend can return, cost a fine for the failed
rehabilitation and may bring extra bad habits." The first argument is the adviser
index: 1 = "The CEO" (matches the user's "incoming call from The CEO"); the
`adviser_name_*` key order (unknown, ceo, warden, governer, chief, doctor,
kingpin) is recorded as `ADVISERS`. There is no dismiss RPC: the speech is
host -> clients only and closing it is local to the client. `ObjectiveRemoved(
"ReadCeosLetter", False)` (the CEO letter) did not remove it. The bot now shows
`The CEO: ...` in its alerts.

### Injecting an adviser message (MKS2, user confirmed)

`ctl send NewSpeechAdded 2 "Hello from the bot: this is an injected Warden message."`
(RPC 117, sent by the bot to the host only) showed up in the host user's game
as a message from the Warden with that exact text. So the **host raises a
`NewSpeechAdded` it receives from a client**, and the second argument can be
free text, not only a language key (a missing key shows the string as is). The
first argument is the adviser index (`ADVISERS`, 1 = The CEO, 2 = The Warden).
The same message sent with `--broadcast` to every other player (adviser 1,
"The CEO here. Great work, Claude. Keep the station OFF.") was not reported by
the user; whether a client displays an event from a non-host sender is open.
Contrast `TransactionAdded` (118): the host shows the amount in its list but
does not change the bank balance, so what a host does with a client-sent event
depends on the handler, not only on the sender.

**SUCCESS: the bot injected a game packet that the host acted on.**
`NewSpeechAdded` (117) sent from the bot (actor 3, `Claude`) reached the real host
`DHost` and was displayed as an advisor message with the bot's own text:
"Hello from the bot: this is an injected Warden message." Confirmed by the user
in MKS2. This is the first client-originated packet in this project that changes
what the host's UI shows; it needs no spoofing of the sender. Reproduce with
`python main.py bot ctl send NewSpeechAdded 2 "your text"`.

The broadcast one, `ctl send NewSpeechAdded 1 "The CEO here. Great work, Claude. Keep
the station OFF." --broadcast` (adviser 1 = The CEO, sent to every other player, not
only the host), was also seen by the user in MKS2. Which screen showed it (host
`DHost`, client `RealClient`, or both) is still to be confirmed; if the client
displays it, a client accepts `NewSpeechAdded` from a non-host sender.

**Confirmed: both screens showed the broadcast message** (host `DHost` and client
`RealClient`, MKS2). So a client accepts `NewSpeechAdded` (117) from a non-host
sender (the bot, actor 3), and the host accepts it too: the sender actor is not
checked for this RPC, and the bot's `--broadcast` reaches every player. Events
whose handler only displays (speech, and the amount in the transaction list for
118) can be injected; events that change authoritative host state (the bank
balance via 118 or `Finance`/`World` directory data) were not applied.
Untried candidates for the same effect: other display-only events (`TransactionAppended`
119 as a text in the list, `ObjectiveRemoved` 21 on clients, `MarkerCreatedPos` 23).

### Tunnel Search on All Sectors (user action, MKS2, `mks2-bot2.sqlite`)

The only change in that window is the `Contraband` directory: packet **9953**
`Contraband {ts=True, d1=0.535497, d2=0.767994}`, then packet **9961**
`Contraband {ts=False, d1=0.535601, d2=0.768225}` (the bot sees it as host ->
client). `ts` is the net key of `TunnelSearch` (the search settings class, with
`s` Shakedown and `db` DrugBust), and it is a one-update trigger: raised for
about eight packets and cleared by the host. "All Sectors" is not in the
packet; the order is sector-wide, so there is no per-sector id. The player's
request itself (client -> host) is only visible in the proxy capture of that
client, not in the bot's. `d1` / `d2` are slowly drifting floats (0.5353 ->
0.5358, 0.7679 -> 0.7688 over 60 packets), possibly search/detection levels.

### Cables silently dropped in MKS2

The farm agent's cable and battery jobs and the bot's own `ctl build line 5 70 6 1
-n ElectricalCable`, a 1x1 cable, a Light and a Capacitor at (5..12, 70..72) never
reached the host's `ConstructionSystem` (`Jobs` stayed at the 3 foundations)
although foundations and generators from the same session were accepted. The
earlier game accepted the same cable jobs. Causes not found yet: the location
(near the south-west corner) or land ownership in this game, a rule after the
bot re-joined as actor 4, or the host's reloads (every `ctl refresh` makes the
host "prepare the save" again, which the agent suspected of wiping queued jobs).

### Grants by name (MKS2)

**`AcceptGrant` takes the grant's full objective name, `Grant_` prefix included.**
`ctl send AcceptGrant Grant_GreenMachine` made `Grant_GreenMachine` `Completed` at once
(its solar / wind / hybrid tasks were already met: 10/10/10) and the balance rose by
9,464 (80,001,552 -> 80,011,016). The bare names the Haiku agent tried
(`greenMachine`, `GreenMachine`, `greenmachine`, `administration`, `ecoFriendly`) and
`bootstraps` do nothing (the host ignores an unknown objective name, `sent: true`
only means the bot sent it). The earlier guess "the grant name is `bootstraps`"
(journal "Accepting the first grant") was the objective `Grant_bootstraps` without
its prefix.
- The `ctl action AcceptGrant` choices only listed the live `target_*` entries
  because they come from the game state; the full list is the game script
  `data/grants.lua` (`Objective.CreateGrant(name, advance, completion)`, parents,
  `SetPreRequisite`, `Require*` conditions) plus the DLC grants named in the
  binary. `src/protocol/grants.py` is generated from both (29 grants:
  bootstraps 20000/10000, Administration 5000/5000, FirstCellBlock, Health,
  Bailout 50000/50000 for debt, Maintenance, Visitation, Basic/Enhanced/Advanced
  Security, PrisonerWorkforce, EducationReformProgram 15000/40000, PrisonLabour,
  FurnitureManufacturing, ReduceStaffStress, Short/LongTermInvestment,
  NutritionResearch, DrugSearch, ContrabandSupply, CellBlock50-500, and the DLC
  EcoFriendly, FirstInsaneCellBlock, GivingSomethingBack, GreenMachine, TrackerPilot).
- The bot now lists them all as `AcceptGrant` choices (`Grant_x: Title`), accepts any
  spelling (`greenmachine` -> `Grant_GreenMachine`, `target_*` kept) and `ctl names
  grants` prints the table.
- The Haiku test of "pick the easiest grant" found Green Machine on its own (compared
  seven grants) but could not accept it because of the name; the fix above is that.

### Doors, workmen and intake (tips from the game's owner, MKS2)

- Buildings stuck on **"Requires Entrance"**: the housing foundations had no door and the
  farm agent's battery hall had only a `JailDoor`; about 26 Workmen stood outside it
  (x 30-34, y 50-52) while 360 `Construct` work items sat unclaimed. **Workmen cannot open
  jail doors** (only guards and above); workmen, staff and guards open a `StaffDoor`
  (prisoners cannot); every entity opens a plain `Door`. Staff and prisoners cannot pass
  through walls (the "Super Guards" toggle, default off, lifts that). Workmen blocked at a
  jail door wait for a guard to open it. Fix tried: `Door` on each new foundation's bottom
  edge and a `StaffDoor` at the hall's top edge (delivery pending when logged).
- **Intake**: `Save Intake.IntakeType` was 4 (AllAvailable), so prisoners kept arriving
  (37 -> 59) with no cells; deaths and escapes cost reputation and income. Paused with
  `IntakeTypeChange 0` (`None`; the host showed `IntakeType=0` after a refresh). The
  bot rejected the named form (`None` is not a whole number) because the arg had no
  choices; `intake` is now a choice list (`INTAKE_TYPES`), so `ctl send IntakeTypeChange None`
  works.
- **Hints in the bot**: `src/bot/hints.py` holds these rules; they come back as `hints` in
  `ctl action NAME`, in the replies of `ctl send`, `ctl build` and `ctl hire` (matched by
  action, tool and object name, e.g. JailDoor, Battery, PowerStation) and from
  `ctl hints [doors|power|people|grants|build]`, so the agent can steer itself.

Intake names (user): the game's intake screen offers **Closed / Fill Capacity / Total
Prisoners / Num Per Day / All Available** (modes 0-4; the binary's enum calls 0 `None`).
`INTAKE_MODES` holds the screen labels, and `IntakeTypeChange` accepts either spelling
(`Closed`, `fill capacity`, `FillCapacity`, `None`). TODO (user): the intake screen also
controls which prisoner categories are taken (`Save Intake/Categories`:
`PrisonerCategory` MinSec / Normal / MaxSec / PrisonerTransfer with `Pool`, `Ratio`,
`NextIntake`, `Queue`); not wired into the bot yet. After `IntakeTypeChange 0` the host
reported `IntakeType=0`; the prisoner count still rose from 59 to 67 from arrivals already
on the way.

### Staff needs and exhausted workmen (MKS2, user: `el` == EnergyLevel)

- Live `ObjectData` of every staff member carries `el` **EnergyLevel** (0 = exhausted; a
  rested person reads 50-100: Warden 51.7, Accountant 85.4), `rs` RestState (1 = the save's
  `RestStateRequired`; 0 otherwise, the Accountant who the save calls `RestStateResting`
  reads 0 live) and `ca` the current need Action (25 for the 18 busy workmen). All 26
  Workmen read `el=0`, `rs=1` (save: `RestState='RestStateRequired'`, `Needs/Action=
  'StaffDuties'`, `Needs/BreakTime` about -17360, i.e. a break overdue for days): they
  cannot rest because no Staffroom exists (`Staffroom`: 4x4 indoor, seats, DrinkMachine)
  and were also stuck at the jail door. Three Guards were hired so the door can be opened.
- Bot: `ctl staff` / `GET /staff` lists every staff member with `energy`, `rest_state`,
  `action`, `status` (exhausted / tired below 25 / ok) and per-type counts. Staff-related
  commands (`ctl hire`, BeginResearch, ToggleResearchDesired, reform/guard actions)
  attach a compact `staff_status` to every third reply, and the hire hint tells the
  agent to check `ctl staff` and build a Staffroom.

Entrance hint (user): `ctl build foundation` and `room` replies, the door objects and `ctl hints
entrance` now tell the agent to give every building a valid, reachable entrance right away
and to match the door to who it serves: workmen need a Door or StaffDoor to build it (never
only a JailDoor); staff rooms a StaffDoor or Door; prisoner rooms (cells, dormitories,
canteen, shower, yard) a Door or JailDoor, since prisoners cannot open StaffDoors; guards
open any door. Source of the rules: the game owner's notes above and the MKS2 stall.

### Green power needs a Transformer (game text, user pointer; MKS2)

Why the farm never powered the buildings even once joined by cable: the game's own text
(`d11.txt`) says "their power must first flow through a **Transformer** before it can be
used within your prison" (`buildtoolbar_popup_uts_SolarPanels/WindTurbine/SolarWindHybrid`).
`buildtoolbar_popup_uts_Transformer`: converts green power into appliance-friendly energy,
several sources per Transformer, **input limit 5000 units**, "Electrical cables must be
connected in the direction shown by the attached arrow images". `..._Battery`: stores the
excess converted by Transformers, "must be placed **adjacent to a Transformer** to function"
(staff alert `GreenEnergy02`: same as Capacitors and Power Stations). `..._PowerExportMeter`:
sells stored energy back to the grid for money, "must be wired to a Transformer that has
Batteries connected". `d11_powerstation_overloaded_two_transformers`: "Overloaded,
Transformers must not be on the same circuit". Utility limit: 128 of each source type
(`d11_utilitylimits_body`). Staff alerts `GreenEnergy01/02` say the same. The Transformer's
panel shows `d11_transformer_input_power` (Production), `output_power` (Expenditure) and
`spare_power` (Excess). Consequence for the 30 generators: they must go into a Transformer
(indoors, e.g. in the battery hall) whose output cable feeds the prison network, and
the farm's cables must not touch the prison's directly. Hint added to the green objects.

### Timed green grants completed (MKS2)

With no PowerStation ever built in MKS2, the clocks ran by themselves at game speed 10:
`Grant_EcoFriendly` (`TimePassedGreen`, `Deadline 7200` = 5 days, `GreenDeadline`
20879.9) read `Completed` by game minute 24385, and `target_PowerStation`
(`Deadline 14400` = 10 days, `GreenDeadline` 23972.4) read `Completed` at 24499, a few
minutes after its deadline (the grant flips on the next update). The completion
minute is exactly the acceptance/last-station minute plus the deadline, so the progress
node needs no polling, only waiting. Current MKS2 grants: Completed GreenMachine,
EcoFriendly, target_SolarPanels, target_WindTurbine, target_PowerStation; open
Grant_Administration, target_ExportPower1-3, target_PassReform, target_ChargeBattery
(`target_GreenEnergySource` has not appeared in this game's list yet).

### Transformer working; missing entrances (MKS2)

- A Transformer (object 389, centre 26,41, inside the battery hall) shows `Powered`, `On`,
  `Demand 5`, `Capacity` 1750-4000, `InputPower` 1750-4000 and `ExcessPower` = Input -
  Demand (net keys `dem`, `cap`, `inppwr`, `excspwr`). `InputPower` equals the farm's
  summed generator `Capacity` (10 x 75 + 10 x 75 + 10 x 250 = 4000; 1750 at another
  reading, i.e. what the sources deliver changes over the day), so the farm cables do reach
  the Transformer, and 5 of the hall's 20 lights then read `Powered`. `lnkpem` (linked
  PowerExportMeter) is false until an export meter is wired.
- **Stuck builders**: the Administration agent's five office foundations (2,44 6x6; 10,44;
  46,4; 54,4; 2,56 7x7) had no door, so all of them sat at 3-45 cells left. A `StaffDoor`
  in the middle of each bottom edge (`ctl build place 5 49 -n StaffDoor` ...) was placed,
  and within about 40 s four foundations had left the queue and the fifth fell from 45 to
  13 cells left. Rule confirmed: check every foundation job for a door on its edge (compare
  `ConstructionSystem Jobs` rectangles with the door objects in `Save Objects`).

### Grant_Administration completed (Haiku 5.5, MKS2)

Open task was `Grant_Administration_offices` (`RequireRoomsAvailable("Office", 2)`): two free
Office rooms. The agent built two 6x6 foundations (2,44) and (46,4), a Door at each bottom
edge, zoned 4x4 Offices at (3,45) and (47,5) with OfficeDesk, OfficeChair, FilingCabinet.
`Grant_Administration` read `Completed` and `money +5000 finance_cost_grantcompletion`
appeared (start payment 5000 was already paid on accept; `completion` 5000 per
`grants.lua`). Lesson (again): a foundation stalls on its middle row until it has a door;
the Door unstuck it and the floor finished within minutes. Two other 6x6 foundations
(10,44) and (54,4) were left without doors by the agent; I put StaffDoors on them
earlier. Open now: target_ExportPower1-3, target_ChargeBattery, target_PassReform.

### Handoff: what is still missing in the bot (user is resetting the context)

The bot features I still think are missing are filed in `TODO.md` under "Missing bot features":
a map with objects and cables (`ctl map`, `ctl network`), object footprints and placement checks,
one-call object state, verified build jobs (no more silent drops), an entrance checker, batch build
retries, less reliance on `ctl refresh`, auto-reconnect, prisoner data and unhoused-prisoner
detection, intake categories, a grants dashboard, reform and research dashboards, staff and
policy commands, the export / battery chain, and the remaining unnamed keys. The next goal is
"Complete Grant 'Basic Detention Centre'" = `Grant_bootstraps` (title from the language file).
Facts to carry: grant names are the full objective names; every building needs a door workmen
and its users can open; green power needs a Transformer; intake is Closed in MKS2 (59-67
prisoners, no cells); 3 Guards, 26 Workmen, an Accountant, a Warden are hired; open grants
are target_ExportPower1-3, target_ChargeBattery, target_PassReform (a Haiku agent was working on
them); completed: GreenMachine, EcoFriendly, Administration, SolarPanels, WindTurbine,
PowerStation.
