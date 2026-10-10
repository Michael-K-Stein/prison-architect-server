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
