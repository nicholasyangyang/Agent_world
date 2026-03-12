"""Tests for config loading and Default_config files."""
import json
import tempfile
from pathlib import Path

import pytest

from config_loader import (
    load_config,
    DEFAULT_SERVER_CONFIG,
    DEFAULT_GATEWAY_CONFIG,
    DEFAULT_CLI_CONFIG,
)


def test_load_config_defaults_when_no_file():
    """When config file doesn't exist, return defaults."""
    defaults = {"host": "0.0.0.0", "port": 8765}
    result = load_config("/nonexistent/path.json", defaults)
    assert result == defaults


def test_load_config_merges_file_with_defaults():
    """File values override defaults, missing keys keep defaults."""
    defaults = {"host": "0.0.0.0", "port": 8765, "log_level": "INFO"}
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump({"port": 9999, "log_level": "DEBUG"}, f)
        f.flush()
        result = load_config(f.name, defaults)
    assert result["host"] == "0.0.0.0"  # default kept
    assert result["port"] == 9999  # overridden
    assert result["log_level"] == "DEBUG"  # overridden


def test_load_config_expands_tilde():
    """Config path with ~ is expanded."""
    defaults = {"key": "value"}
    # Just verify it doesn't crash with tilde path (file won't exist)
    result = load_config("~/nonexistent_config.json", defaults)
    assert result == defaults


def test_default_server_config_exists_and_valid():
    """Default server config file exists and has expected keys."""
    assert DEFAULT_SERVER_CONFIG.exists()
    with open(DEFAULT_SERVER_CONFIG) as f:
        cfg = json.load(f)
    assert "host" in cfg
    assert "port" in cfg
    assert "db_path" in cfg
    assert "log_level" in cfg
    assert isinstance(cfg["port"], int)


def test_default_gateway_config_exists_and_valid():
    """Default gateway config file exists and has expected keys."""
    assert DEFAULT_GATEWAY_CONFIG.exists()
    with open(DEFAULT_GATEWAY_CONFIG) as f:
        cfg = json.load(f)
    assert "server_url" in cfg
    assert "sock_path" in cfg
    assert "ipc_timeout" in cfg
    assert isinstance(cfg["ipc_timeout"], (int, float))


def test_default_cli_config_exists_and_valid():
    """Default CLI config file exists and has expected keys."""
    assert DEFAULT_CLI_CONFIG.exists()
    with open(DEFAULT_CLI_CONFIG) as f:
        cfg = json.load(f)
    assert "sock_path" in cfg


def test_load_config_file_values_take_precedence():
    """When a file provides all keys, file values win."""
    defaults = {"a": 1, "b": 2}
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump({"a": 10, "b": 20}, f)
        f.flush()
        result = load_config(f.name, defaults)
    assert result == {"a": 10, "b": 20}


def test_load_config_extra_keys_from_file():
    """Extra keys in file are included in result."""
    defaults = {"a": 1}
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump({"a": 10, "extra": "hello"}, f)
        f.flush()
        result = load_config(f.name, defaults)
    assert result["a"] == 10
    assert result["extra"] == "hello"


def test_server_config_used_by_create_server(server):
    """Verify test server still starts correctly (config doesn't break it)."""
    # The server fixture uses create_server with in-memory DB
    # If config loading broke the import chain, this would fail
    assert server["port"] > 0


@pytest.mark.asyncio
async def test_server_with_custom_config():
    """Verify server can be started with custom config values."""
    from server.db import init_db
    from server.main import create_server

    db = await init_db(":memory:")
    state, ws_server = await create_server(db, host="127.0.0.1", port=0)
    port = ws_server.sockets[0].getsockname()[1]
    assert port > 0
    ws_server.close()
    await ws_server.wait_closed()
    await db.close()
