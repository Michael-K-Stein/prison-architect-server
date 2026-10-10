@AGENTS.md

## Claude Code notes

- Commit or push only when asked. Never stage `journal/` edits you didn't make;
  the user often has uncommitted journal work in progress.
- `git add` specific paths and check `git status` before committing; a failed
  pathspec silently leaves files out of the commit.
- When orchestrating subagents, give each one a disjoint set of files and the
  exact module paths and public names it may rely on from the others.

## Opening the IDA database (idalib)

The IDA 9.0 database is `../ida-work/db/pa.i64` (game exe:
`C:\Users\mkupe\Games\PrisonArchitect\...\Prison Architect64.exe`). The default
`python` (3.14/3.12) can't use idalib; the `ida` package is installed for
**Python 3.11 only**. Run scripts with `py -3.11` (or `py -V:3.11`):

```sh
py -3.11 script.py [args]      # script starts with: from ida import *
```

- Open with `open_database(r"C:\...\pa.i64", False)`, close with
  `close_database(False)` (no save). Import `idautils/idc/ida_hexrays/...`
  *after* `open_database`. Hex-Rays works: `ida_hexrays.decompile(ea)`.
- Opening takes ~30-60 s and prints a noisy banner. Keep scripts outside the
  repo (e.g. `C:\Users\mkupe\scratch`), print only what you need, and give the
  command a timeout of ~110 s (or run it in the background).
- Existing helpers live in `../ida-work/scripts/` (`xr.py` xrefs, `dec.py`
  decompile, `dump.py` functions/strings -> `../ida-work/out/dump.json`).
- Never open the db from two processes at once; a leftover lock means a
  previous run is still alive.
- Pointers to strings usually show up as code xrefs (`XrefsTo(ea, 0)`), not data.
