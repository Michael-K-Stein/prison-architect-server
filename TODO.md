# TODO

Open work for the bot and the protocol notes. Remove an item when it is done and put the
finding in `journal/journal2.md`.

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

### Next goal (user): complete Grant "Basic Detention Centre"
That is `Grant_bootstraps` (title from the language file; 20000 advance, 10000 on completion; tasks
HoldingCell/PaddedHoldingCell, Shower, Yard, Kitchen, Canteen rooms that meet their rules, 2 Guards,
2 Cooks). MKS2 does not offer it in `AcceptGrant` choices (`AcceptGrant bootstraps` did nothing;
the full name is `Grant_bootstraps`, any spelling works in the bot); the first goal is to find
out whether MKS2 already had it done or why it is not listed. Use `ctl hints`, doors for every
building, a Transformer for green power, intake Closed while prisoners lack cells.

### Unknown ObjectData keys `p`, `v`, `o` (user, BrowserStat -> ObjectData/<id>)

They exist on workmen (and other staff and prisoners), change very rapidly, and have no save
name. Not found in any `ObjectData` constructor decompiled so far (`sub_1407D1E10` WorldObject
and the Person / Door / Container / electrical classes), so they come from a function that registers
them without a long name. Facts so far (MKS2, `mks2-bot4.sqlite`, 26 workmen + staff) and
hypotheses already **rejected** are in the journal ("Unknown ObjectData keys p, v, o"). Next step:
find the registering function in IDA (xrefs to the 1-char strings `"p"`, `"v"`, `"o"` at
`0x140ADA774`-ish in `.rdata` next to `"ss"`, `"rs"`, `"s1"`) and read which members they bind.
