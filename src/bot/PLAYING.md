# Playing Prison Architect through the bot

For an agent with a shell. The bot joins a game hosted by a real client and
acts as a second player; everything below goes through `python main.py bot`.
Every command prints JSON. Never guess ids: look names up with `ctl names`.

## Start and stop

```sh
python main.py bot --region au --name-server auto --password 123 serve --room A &   # keep running
python main.py bot ctl state        # check it is connected (wait ~10 s after start)
python main.py bot ctl quit         # leave the game when done
```

## Look

- `ctl state`: balance, game time (`time_index`, minutes; a day is 1440),
  speed, `rooms` (with each cell's `occupant` prisoner), `problems` (room
  errors, objects without power), `alerts` (messages from your staff),
  `object_names` (counts), `recent` events.
- `ctl refresh`: re-read the whole game from the host. `rooms` and `problems`
  only update on a refresh, so refresh after building or waiting.
- `ctl events --since N`: new events after event number N (`last` in the reply).
- `ctl state <System> [path] --depth 1`: raw state (`Save` is the full save).
- `ctl keys` explains the short keys (`st`, `ci`...) in raw state, which `ctl state` now shows as `SubType (st)`.
- `ctl names objects bed` / `materials concrete` / `rooms cell` / `intake`.

The map is a grid of cells, `x` to the right and `y` down; the map size is in
`ctl state Save --depth 0` (`NumCellsX`, `NumCellsY`). Build on empty ground
away from existing buildings.

## Names

Give things names instead of juggling indexes and uIds: `ctl name set Main_Power_Station 52`
(`--room` for a room index, or `uId,index`), `ctl name list`, `ctl name rm NAME`. A name works
anywhere an object is expected (`ctl send ElectricalSwitch Main_Power_Station off`,
`RemoveRoom Holding_Cell`) and appears in `problems`, the event feed and object dumps
(`Name`). Names are saved per game in `bot-names.json`.

## Act

```sh
python main.py bot ctl build foundation X Y W H            # floor + walls round the edge
python main.py bot ctl build room X Y W H -n Cell          # zone a room inside walls
python main.py bot ctl build place X Y -n Bed              # one object
python main.py bot ctl build line X Y W H -n ElectricalCable   # cables/pipes as a line
python main.py bot ctl hire Guard 2                         # hire staff: Guard, Cook, Doctor, Warden, Workman
python main.py bot ctl send GameSpeedChange 10             # 0 paused, 1, 2, 5, 10
python main.py bot ctl send IntakeTypeChange FillCapacity  # prisoners arrive daily at 08:00
python main.py bot ctl action NAME                         # an action's arguments and choices
```

Workers need time: wait (`ctl wait 30`, or speed up) and check `ctl events`
and `ctl refresh` before the next step. A job the game refuses (bad spot,
unfinished floor) just never appears; objects inside a room need its floor
finished first.

## Room requirements

A zoned room only counts (and a grant's room objective only completes) when it
meets the game's rules: `ctl rules` lists every room, `ctl rules Kitchen` one.
`ctl state` `problems` says what each of your rooms lacks ("Kitchen #9: lacks
Fridge, Sink"). Notably: HoldingCell needs 5x5 inside, Toilet and Bench; Yard
5x5 and `Secure` (fenced); Kitchen Cooker, Fridge, Sink (and power for the
cooker); Canteen ServingTable, Table, Bench or DiningChair; Shower ShowerHead.
Clear an old building with `ctl demolish X Y W H`, then `-n DemolishWalls`,
then `-n ClearIndoorArea` (as the game's own tools do).
Power: a cable must touch each device (only lights work a few cells away);
`ctl wire X1 Y1 X2 Y2` lays cable along x then y between two cells, end it on a
cell next to the device (check the objects' positions with `ctl state`).
Walls block a cable's reach to lights; doors do not. A cable along a hallway may
power lights in a room through its door, but a room with no door on the cable's
side needs its own cable run inside.
A PowerStation has a Capacity (50); past it the grid is overloaded and ALL power
cuts out (`problems` says so). Remove load, add Capacitors, or add another
PowerStation on completely separate cables: crossing lines short-circuit.
`ctl research [Name]` shows what a research needs: most are blocked until the
matching staff member is hired (`ctl hire Chief|Lawyer|Accountant|Foreman|
Psychologist`) and sits in his office. Research (`BeginResearch`) is charged up front, is not refunded, and the balance
can go negative: read `balance` and the cost first and start one at a time.
A negative balance silently blocks ALL building (jobs never reach the host);
keep `balance` above 0.
Staff are hired with `ctl hire Guard 2`.

## Recipe: a prisoner cell

Check progress with `ctl area X Y 5 5`: one row of letters per map row,
`W` wall, `F` floor (a door's cell also reads `F`), `B` frame (walls not
built yet), `D` other ground, `.` nothing. At 10x speed, `ctl wait 30` lets
about 300 game minutes pass.

1. `build foundation X Y 5 5`: a 5x5 building, inside cells `X+1..X+3`,
   `Y+1..Y+3`. Speed up and wait until `ctl area X Y 5 5` shows `F` inside and
   `B` round the edge (a minute or two at 10x).
2. `build place X+2 Y+4 -n JailDoor` (a door in the bottom edge). **The walls
   are only built once the building has a door**: the `B` edge then turns
   into `W`. Wait for that.
3. `build room X+1 Y+1 3 3 -n Cell`, `build place X+1 Y+1 -n Bed`,
   `build place X+3 Y+1 -n Toilet`. Wait until `ctl events` shows the Bed and
   Toilet `object added` and a `room created: ... Cell` line.
4. `send IntakeTypeChange FillCapacity` (if not already), `send GameSpeedChange 10`
   and wait for 08:00 game time (`time_index` modulo 1440 = 480). New prisoners
   show as `object added: ... Prisoner`; they only come when a cell is free.
5. `ctl refresh`: the new Cell room's `occupant` is the prisoner assigned to it.

The `Foundations` entry in `ctl state ConstructionSystem` stays listed (with
`Hidden: true`) after the building is done; don't wait for it to disappear.

A cell is only fully usable with water for the toilet (a `WaterPumpStation`
with power, pipes to the toilet) and a canteen with a kitchen to eat in;
`problems` and `alerts` say what is missing.

## Green power needs a Transformer

SolarPanels, WindTurbines and SolarWindHybrids must feed a **Transformer** (id 389, 2x2, indoor,
input limit 5000 units); only the Transformer's OUTPUT can power the prison, and its two
sides have arrows (cable direction matters). Batteries must be adjacent to the Transformer;
a PowerExportMeter is wired to a Transformer that has Batteries. Two Transformers must not
share a circuit. `ctl hints green` has the details; the hints are attached to every green
object you place.

## Green Energy Goals (the `target_*` grants)

From the game text: 3 solar panels, then 3 wind turbines (each unlocks the next
item), export 1000 / 2500 / 5000 units of power (PowerExportMeter), 25 prisoners
pass the Solar Panel Development reform program, 10 of each green source,
**no PowerStation running for 10 game days** (`ctl send ElectricalSwitch NAME off`;
the prison must run on green sources), and 100 batteries fully charged. An
object's index is reused after it is removed: check `current` in `ctl name list`.

## Grants

`ctl names grants` lists every grant (payments in `start`/`done`); `ctl send AcceptGrant NAME`
takes the name in any spelling (`greenmachine`, `Grant_GreenMachine`). A grant whose tasks
the prison already meets completes at once; read the tasks in `src/protocol/grants.py`
(`GRANTS[...]['tasks']`) and compare with `ctl state`. Check `grants` in `ctl state` after
accepting: an unknown name is ignored without an error.

## Hints

Replies from `ctl send`, `ctl build`, `ctl hire` and `ctl action NAME` carry a `hints` list
with the rules that matter for that command; `ctl hints` prints them all (topics: doors,
power, people, grants, build). Read them before building: workmen cannot open JailDoors,
a building needs a Door or StaffDoor first, Batteries are indoor only, unhoused prisoners
die (pause intake with `ctl send IntakeTypeChange Closed`).

Entrances: every foundation or room needs a door that works for everyone it serves. Workmen
(to build it) need a Door or StaffDoor, never only a JailDoor. Staff rooms take a
StaffDoor or Door. Rooms prisoners must reach (cells, dormitories, canteen, shower, yard)
need a Door or JailDoor; prisoners cannot open StaffDoors. `ctl hints entrance` repeats this
and it is attached to `ctl build foundation|room` replies.

Object hints come from the game's own tooltips (`src/bot/data/object_hints.json`, built by
`python -m src.bot.hintgen "<language dir>"`). A `ctl build` reply carries `object_hints`
for the objects in that build, but only the first time the session uses each one, plus a
reminder after 25 more build replies or 30 minutes; at most three per reply. Read the full
text of any object with `ctl hints --object Transformer`.
