# AGENTS.md

A self-hosted multiplayer server for Prison Architect. The game talks to Photon
(Exit Games); a hosts-file redirect of `ns.exitgames.com` sends it to us instead.
The repo also reverse-engineers the game's RPC traffic: a logging proxy, a SQLite
packet recorder, and an interactive bot that joins real games.

## Layout

`main.py` is the only Python file at the root. Do not add others there.

```
main.py              typer CLI: local | proxy | bot | capture (wizard when run bare)
src/env.py           shared .env loader (existing env vars win)
src/server/          upstream.py (Name Server via DoH), game_server.py (room rules),
                     server.py (PrisonArchitectServer, app ID)
src/protocol/        rpc_table.py (generated RPC table), rpc.py (typed codec),
                     snapshot.py (zlib tree / arg decoding), events.py (labels, log lines)
src/capture/         schema.py, recorder.py (writer), reader.py (Capture/follow),
                     render.py, cli.py (`capture tail|sessions`)
src/bot/             speed, slider (prompt_toolkit), formatting, session, flow,
                     actions (menu registry), cli.py (`bot`, `bot regions`)
tests/               one test file per area
journal/             reverse-engineering notes; the source of truth for protocol facts
captures/            recorded runs (runN.sqlite); data, not code
deploy/              Docker and Pterodactyl egg (both run `python main.py local ...`)
```

Imports are absolute from the repo root: `from src.protocol.rpc import build`.
The Photon client/server comes from pyPhotonRealtime (pinned tag in `requirements.txt`).
Fix generic Photon behaviour there, not here; `src/` holds only game-specific rules.

## Commands

```sh
python -m pip install -r requirements.txt     # plus pytest for the pytest-style tests
python main.py local                          # run the server
python main.py proxy --record captures/runN.sqlite
python main.py capture tail captures/runN.sqlite
python main.py bot                            # needs PHOTON_APP_ID (env or .env)
```

## Checks (run all before pushing)

CI (`.github/workflows/`) uses ruff **0.16.10**. Use that exact version
(`python -m ruff --version`), not a global one:

```sh
python -m ruff check --select E9,F63,F7,F82 .
python -m ruff format --check .
python -m pytest tests -q
python tests/test_prison_architect.py   # script-style; prints "ok"
python tests/test_capture.py
python tests/test_pa_events.py
```

CI only runs the three script-style files, so `pytest tests` is the only thing
that covers `test_bot.py` and `test_pa_rpc.py`. Run it.

## Conventions

- Python 3.12 (`typing.override` is used). `from __future__ import annotations` in modules.
- Match the surrounding style: short docstrings that say *what it is*, comments
  only for non-obvious protocol facts, typer `Annotated` options.
- One responsibility per module. Keep public names stable; tests import them directly.
- Wire-format facts (RPC codes, arities, tags) must trace back to a capture or a
  `journal/journal2.md` section. Don't guess them. `rpc_table.py` is generated from
  the journal's "The RPC table" section; change the source, not the table by hand.
- New protocol findings go into `journal/journal2.md` as a new `## ...` section
  titled with the capture or tool and the model that did the work. Record wrong turns in
  the "Mistakes log".
- Never store ciphertext or credentials in captures, code or the journal. `.env` is
  local only (`.env.example` lists the keys).

## Local network gotchas

- The hosts redirect also catches *your* tools. Anything that needs the real
  Name Server must resolve it another way (DoH in `src/server/upstream.py`, or
  an explicit `--upstream` / `--name-server` address).
- `captures/*.sqlite` files may be held open by a running proxy (WAL mode). Read
  them with `Capture`, which is safe alongside a writer.
