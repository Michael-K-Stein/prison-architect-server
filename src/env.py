"""Load ``KEY=value`` settings from the repo's ``.env`` file."""

from pathlib import Path

from dotenv import load_dotenv

ENV_PATH = Path(__file__).resolve().parent.parent / ".env"


def load_env(path: Path) -> None:
    """Put ``KEY=value`` lines of ``path`` into the environment (not overriding)."""
    load_dotenv(path, override=False)
