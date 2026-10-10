# TODO

Open work for the bot and the protocol notes. Remove an item when it is done and put the
finding in `journal/journal2.md`.

## Bugs

- **`/cash` does not work in the proxy terminal** (user report, 2026-10-10, attached to the MKS2
  game). `src/cli/inject_commands.py` `cash AMOUNT [KEY]` injects a `TransactionAdded`
  (`finance_cost_cashflow`) to the client; the effect on the client's balance was not seen.
  Not yet reproduced: check that the event reaches the client (capture `injected` column), and
  recall that a host ignores `TransactionAdded` / `Finance` writes from clients (journal2), so
  only a client-side display may be possible.

## Priorities (user, 2026-10-10)

1. The room goal (one verified room of every type, minimum and lavish; `ctl room`, `ctl building`, `ctl connect`).
2. **The in-game Todo list** (2 items, 1 completed): not in the save (`Objectives/SelectedObjectives` empty, no
   `todo` string in any section) nor in any packet seen; needs a recording while the user adds / ticks / deletes an item.
- **Dropped:** `target_PassReform` (the last open green goal).
- **Deferred:** the Psychologist's Needs report (`ctl needs`).
- **Careful:** `ctl remove` is destructive (a client's `ObjectRemoved` deletes any object on the host).

## Deferred from the MKS2 session (2026-10-10)

- **Utility line optimization** (user): `src/bot/connect.py` is a plain BFS per object (shortest run to the nearest fed
  cell, earlier runs reused). Replace it with A* (or a Steiner-tree heuristic over all targets at once) and a cost
  model: cell price (trunk vs branch; long straight runs through several rooms are cheap to draw, lines may cross
  several foundation borders), overlap protection (never touch the raw green line, never run through generators,
  keep clear of objects a line is `BlockedBy`), extendability (a straight trunk with free neighbouring cells,
  runs along room edges, room for later branches). Keep `plan()`'s output (`line` jobs) so `ctl connect` does not change.

Prioritised after the main tasks (room goal, PassReform, Needs report); each is a thread that was opened and
parked:
- **DLC gating** (user): offer a DLC object / room / research only when the current game supports it. The data
  files tag them (`DLC PrisonWingPriviledges`, `SeaAirLand`, `FreeContentPack_1`, `VersionAdded`); find how a
  game declares its DLCs (save keys, `Version`), then filter `ctl rules`, `ctl names`, `ctl room plan` and refuse
  unavailable placements with a clear message.
- **Tables from the `*_dlc` files** (audit): reform programs (33 programs, the game's index order changes with unlocked
  research, so map by probing `StartReformProgram` + `Save Reform`), needs (33 names, Needs {Size=34} in
  `EntityUpdate`), prefabs (54, the game's own room layouts: `prefabs*.txt`; a good source for designs and the
  `Prefabs` job type). Objects, materials, research and rooms are complete.
- **`ctl needs`** (the Psychologist's report): request `EntityUpdateRequest` for each prisoner and parse the
  `NeedsUpdate` / `Needs` reply (needs prisoners; intake was reopened with FillCapacity).
- **`ctl remove NAME|INDEX`**: a client's `ObjectRemoved` (14) deletes any object on the host (found with the pump);
  wrap it with a confirmation, and a refund check.
- **Verify high priority live** (`ctl priority`, Construction Type -11) once a queue exists; read `WorkQueue.HighPri`.
- **Armoury door mismatch** reported by the player (planned x=9, built x=6): unconfirmed; check `rooms.stages` door x.
- **Finance keys** `v.0`-`v.5`, `v.7`-`v.11`, `tv` still unnamed (journal2 "Finance short keys").
- **`/cash` in the proxy terminal** does not work (see Bugs).
- **The in-game Todo list** (2 items, 1 done) is in no packet or save section: probably client-local.
- **Unknown ObjectData keys `p`, `v`, `o`**, **intake categories**, **layout optimization**, **power hall wiring** (solved
  by hand, journal2): see the sections above.

## Bot

- **Prisoner status and data.** Prisoners have names, ages, needs and reputations. Needs are
  only visible with a **Psychologist on the premises** (hire one: `ctl hire Psychologist`,
  seat him in an Office). The bot should also know when a prisoner has **no free cell**: the
  game shows "There are no free cells for this prisoner" when hovering over the character.
  Find where it lives (live `ObjectData` Person keys such as `ci` / `la`, the save's
  `Bio` / `Needs` children, or a room assignment such as `AssignedRoom`) and add `ctl
  prisoners` plus a `problems` line / hint when prisoners outnumber free cells (deaths and
  escapes cut reputation and income; pause intake meanwhile).
- **Intake categories.** The intake screen controls which prisoner categories are taken (MinSec /
  Normal / MaxSec / transfers; `Save Intake/Categories`: `Pool`, `Ratio`, `NextIntake`,
  `Queue`). Only the mode (`IntakeTypeChange`: Closed / Fill Capacity / Total Prisoners / Num
  Per Day / All Available) is wired.
- **Dismantling objects.** The host creates `DismantleObject` work jobs from its own UI; no
  client request is known (journal2 "Pause point"). Capture a real client dismantling.
- **Unnamed keys.** `Finance.v.<n>` / `tr.*`, `Intake.i`, `NeedsDistribution`, `Visitation.w`,
  `WorkQueue.ri`, `EffectsSystem`, `EventLog` event codes (guesses), `VictorySystem` leftovers.

- **Blocking actions.** Let selected `ctl` commands wait for the work to finish and return the
  result (e.g. `ctl demolish --zone Detention:Canteen --wait` bulldozes a zone and returns when
  its cells are clear, or `build ... --wait` returns `built` / `refused`). Future bot agents use
  them to work synchronously. Every blocking call MUST take a timeout of **at most 9 minutes**
  (reject larger values; on expiry return what is still pending, never hang). Rarely needed:
  jobs are already queued in-game for workmen to pick up, so use it only for the few steps whose
  next action depends on the result (clear a site before building on it, finish a room before
  placing objects, check a job was not silently dropped). Poll `ConstructionSystem Jobs` and
  the object / cell state; see also "Verify build jobs" below.

## Missing bot features (end of the MKS/MKS2 sessions)

Found while running Haiku agents through `ctl`; most cost an agent real time. Roughly by value.

### Seeing the world
- **A map with objects.** `ctl area` shows only floor/wall/frame; cables, pipes, doors and objects are
  invisible, so agents guess adjacency. Add `ctl map X Y W H` (legend: cable, pipe, door kinds, each
  object's footprint from `materials.txt`, room ids) and `ctl network power|water` that flood-fills
  `Save Electricity` / `Save Water` and reports the networks, which generators / Transformer /
  consumers are on each, `InputPower`/`Demand`, and the gaps between networks (the scripts used in
  the journal "Green farm" entries should become this command).
- **Object footprints and placement checks.** Sizes are in `materials*.txt` (SolarPanels 3x2,
  WindTurbine 2x3, Hybrid 3x3...), positions in the save are centres; agents assumed 2x2 and
  1x1. Add sizes to `ctl names objects`, say which cell `place X Y` anchors, and check free cells
  before sending.
- **Object state in one place.** `Powered`/`On`/`Switch`/`Overloaded` (0/1/3), Transformer
  `InputPower`/`ExcessPower`, battery charge, staff `EnergyLevel`: a `ctl object NAME|INDEX`
  that merges live `ObjectData` and the save with long names.
- `speed` in `ctl state` reads null; read `World/ClientData gt` (host speed) instead.

### Utilities layout (cables and pipes)
- **Layout optimization functions** (user request, 2026-10-10). Given the buildings (rooms, doors, lights
  and devices from the save) and the sources (Transformer output, pumps), plan the cable / pipe runs
  instead of hand-placing `ctl wire` lines: a minimum Steiner-style tree per utility that reaches every
  consumer, keeps raw-green and AC networks apart (never touch generators or the Transformer input),
  routes through wall cells beside doors, avoids object footprints, and emits `build line` / `dismantle`
  jobs plus a verification pass with `ctl network`. The MKS2 AC backbone done by hand (spine x=42, trunk
  south and east, feeders per building; journal2 "Removing cables and the hall grid fix") is the
  worked example. Needed first: `ctl map` with objects, and the `dismantle` tool (done).

### Doing things reliably
- **Verify build jobs.** `sent: true` means nothing; the host drops jobs silently. After a build,
  poll `ConstructionSystem Jobs` / object counts and return `queued` / `refused` / `built`
  (cables near the south-west corner were dropped for a whole session; cause unknown).
- **Entrance checker.** `ctl check buildings`: every foundation job and room vs door objects on its
  edge (what unblocked the offices); flag JailDoor-only buildings workmen cannot enter.
- **Batch builds with retry** of refused cells and a progress view (the Haiku agents sent 30-job
  batches and lost half).
- `ctl refresh` makes the host prepare the whole save again every time (hitches the host). Keep rooms,
  problems and Electricity current from live events so refresh is rarely needed.
- Auto-reconnect: a restarted bot returns as a new actor number (3, 4, 5); the control API dies with it.

### Game systems not wired
- **Prisoners** (names, ages, needs, reputation; needs need a Psychologist; "no free cells for this
  prisoner"): see the first TODO. Detect unhoused prisoners and pause intake automatically.
- **Intake categories** (MinSec / Normal / MaxSec / transfers, pools, ratios).
- **Grants**: `ctl grants` that lists every grant with its tasks from `GRANTS` and the live status of each
  `Grant_<name>_<task>` objective, and suggests the cheapest one to finish. `target_GreenEnergySource`
  never appeared in MKS2's list (unlock condition unknown).
- **Reform programs**: `StartReformProgram` takes a program type; `ScheduleProgram` and regime slots;
  instances cannot be removed; Solar Panel Development's type index (10?) is unconfirmed.
- **Research dashboard**: combine `ctl research`, live Progress, the staff member present in an office
  and the in-game "REQUIRED: ..." text; `BeginResearch` vs `ToggleResearchDesired` behaviour is not
  understood (the first sometimes does not register).
- **Staff**: Staffroom for exhausted staff, assignments, patrols, deployment, regime/schedule editing,
  policies (misconduct, privilege, meals), visitation, punishments, tunnel / contraband searches
  (the `Contraband.ts` flag is seen, the client request is not), transport and vehicles.
- **Power export**: how the PowerExportMeter / Transformer / Battery chain really behaves (adjacency,
  arrow direction, `lnkpem`) is only documented from the game text.

### Protocol knowledge
- Remaining unnamed short keys (see "Unnamed keys" above) and the `EventLog` event codes (guessed).
- Client -> host requests we cannot see from the bot: dismantle, bulldoze of objects, tunnel search,
  object move. Needs a real client behind the proxy (the user's plan) and a `ctl raw`-style sender for
  `DirectoryData` systems besides `Construction`.
- `TransactionAdded` / `Finance` / `World` balance writes are ignored by the host; a client cannot
  credit money. The host does show injected display events (`NewSpeechAdded`): possible uses for
  hints to the human player.

### Bot ergonomics
- Hints reach the agent only in replies; add an optional first-run summary (`ctl brief`) with the
  five rules that cost the most time (entrance, Transformer, jail doors, intake, name the grant).
- The object-hint pipeline shows hints once and as reminders; tune thresholds from real agent runs.
- More tests for the control API against recorded captures (`captures/mks2-bot*.sqlite`).

### Fix MKS2's power hall wiring (found by `ctl network`)
The raw-green trunk (x=21) touches the light rows y=35/37/43/45/47 of the power hall, so those
lights are dark. Needs a **cable-removal job** (none known: `demolish` leaves the cable; capture the
user's client removing one) to cut (22,y) on those rows, then an AC spine at x=42 joining them to the
Transformer's output rows (y=39/41, x>=27). The admin hall's lights are on the same raw network
(via y=26 / x=62). The kitchen's Cooker/Fridge sit on a 5-cell cable with no source.

### Unknown ObjectData keys `p`, `v`, `o` (user, BrowserStat -> ObjectData/<id>)

They exist on workmen (and other staff and prisoners), change very rapidly, and have no save
name. Not found in any `ObjectData` constructor decompiled so far (`sub_1407D1E10` WorldObject
and the Person / Door / Container / electrical classes), so they come from a function that registers
them without a long name. Facts so far (MKS2, `mks2-bot4.sqlite`, 26 workmen + staff) and
hypotheses already **rejected** are in the journal ("Unknown ObjectData keys p, v, o"). Next step:
find the registering function in IDA (xrefs to the 1-char strings `"p"`, `"v"`, `"o"` at
`0x140ADA774`-ish in `.rdata` next to `"ss"`, `"rs"`, `"s1"`) and read which members they bind.

- **Recover a loadable save from a capture.** After the MKS2 host crash the newest `.prison` was an hour old;
  the last full save is in the bot's capture (handshake `SaveDataChunk`s). Write a `.prison` (the game's
  text save format) from the decoded `Save` tree so a crashed session can be restored.
