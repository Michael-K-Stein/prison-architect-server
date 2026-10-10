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
python main.py bot ctl send GameSpeedChange 10             # 0 paused, 1, 2, 5, 10
python main.py bot ctl send IntakeTypeChange FillCapacity  # prisoners arrive daily at 08:00
python main.py bot ctl action NAME                         # an action's arguments and choices
```

Workers need time: wait (`ctl wait 30`, or speed up) and check `ctl events`
and `ctl refresh` before the next step. A job the game refuses (bad spot,
unfinished floor) just never appears; objects inside a room need its floor
finished first.

## Recipe: a prisoner cell

1. `build foundation X Y 5 5`: a 5x5 building, inside cells `X+1..X+3`,
   `Y+1..Y+3`. Wait until it is built (no `Foundations` job left in
   `ctl state ConstructionSystem`).
2. `build room X+1 Y+1 3 3 -n Cell`, `build place X+1 Y+1 -n Bed`,
   `build place X+3 Y+1 -n Toilet`, `build place X+2 Y+4 -n JailDoor`
   (the door goes in the bottom wall).
3. `send IntakeTypeChange FillCapacity`, then `send GameSpeedChange 10` and wait
   for 08:00 game time. New prisoners show as `object added: ... Prisoner`.
4. `ctl refresh`: the cell's `occupant` is the prisoner assigned to it.

A cell is only fully usable with water for the toilet (a `WaterPumpStation`
with power, pipes to the toilet) and a canteen with a kitchen to eat in;
`problems` and `alerts` say what is missing.
