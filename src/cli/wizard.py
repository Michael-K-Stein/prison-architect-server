"""Interactive setup wizard, shown when `main.py` runs bare in a terminal."""

from __future__ import annotations

from dataclasses import fields

import typer

from src.cli.local import start_local
from src.cli.options import CommonOptions
from src.logs import LOG_LEVELS


def interactive(defaults: CommonOptions) -> None:
    # Imported lazily: only needed for the wizard, and keeps --help snappy.
    from InquirerPy import inquirer
    from InquirerPy.validator import NumberValidator

    def ask_int(message: str, default: int) -> int:
        return int(
            inquirer.text(
                message=message,
                default=str(default),
                validate=NumberValidator(message="Enter a whole number"),
            ).execute()
        )

    typer.secho("Prison Architect server setup", fg=typer.colors.CYAN, bold=True)
    opts = CommonOptions(
        verbose=inquirer.select(
            message="Log level:", choices=list(LOG_LEVELS), default=defaults.verbose
        ).execute(),
        listen=inquirer.text(
            message="Listen address:", default=defaults.listen
        ).execute(),
        ip=inquirer.text(
            message="Redirect IP (127.0.0.1 or your public IP):", default=defaults.ip
        ).execute(),
        timeout=ask_int("Keep-alive timeout (seconds):", defaults.timeout),
        region=inquirer.text(message="Region name:", default=defaults.region).execute(),
        max_players=ask_int("Max players per room:", defaults.max_players),
    )
    print_equivalent(opts)
    start_local(opts)


def print_equivalent(opts: CommonOptions) -> None:
    flags = {
        "verbose": "-v",
        "listen": "-l",
        "ip": "-i",
        "timeout": "--timeout",
        "region": "-r",
        "max_players": "--max-players",
    }
    args = ["local"]
    for f in fields(opts):
        args += [flags[f.name], str(getattr(opts, f.name))]
    typer.secho(
        "Equivalent command: python main.py " + " ".join(args),
        fg=typer.colors.BRIGHT_BLACK,
    )
