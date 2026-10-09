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
