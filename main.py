"""Entry point: ``python main.py`` (see ``src/cli`` for the commands)."""

from src.cli.app import app
from src.env import ENV_PATH, load_env

if __name__ == "__main__":
    load_env(ENV_PATH)
    app(prog_name="main.py")
