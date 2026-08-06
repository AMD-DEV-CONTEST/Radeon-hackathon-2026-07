from pathlib import Path

from dotenv import load_dotenv


def load_env():
    xdg_config = Path.home() / ".config" / "fluxreel" / ".env"
    if xdg_config.is_file():
        load_dotenv(xdg_config, override=True)
