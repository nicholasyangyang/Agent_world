"""Shared config loading utility."""
import json
from pathlib import Path
from typing import Any


def load_config(config_path: str | Path, defaults: dict[str, Any]) -> dict[str, Any]:
    """Load a JSON config file, merging with defaults.

    Args:
        config_path: Path to the JSON config file.
        defaults: Default values for all config keys.

    Returns:
        Merged config dict (file values override defaults).
    """
    config = dict(defaults)
    path = Path(config_path).expanduser()
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            user_config = json.load(f)
        config.update(user_config)
    return config


# Default config file paths (relative to project root)
PROJECT_ROOT = Path(__file__).parent
DEFAULT_SERVER_CONFIG = PROJECT_ROOT / "Default_config" / "server_main_config.json"
DEFAULT_GATEWAY_CONFIG = PROJECT_ROOT / "Default_config" / "client_gateway_config.json"
DEFAULT_CLI_CONFIG = PROJECT_ROOT / "Default_config" / "client_cli_config.json"
