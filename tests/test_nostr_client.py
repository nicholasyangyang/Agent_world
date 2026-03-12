"""Tests for nostr_client — key management and client setup."""
import json
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock

from nostr_client import load_or_create_keys, npub_short


def test_npub_short():
    assert npub_short("npub1abcdef123456") == "npub1abcdef1.."


def test_npub_short_long():
    npub = "npub1" + "a" * 60
    assert npub_short(npub) == npub[:12] + ".."


def test_load_keys_from_file(tmp_path):
    """Keys loaded from existing key.json."""
    from nostr_sdk import Keys
    keys = Keys.generate()
    key_file = tmp_path / "key.json"
    key_file.write_text(json.dumps({
        "nsec": keys.secret_key().to_bech32(),
        "npub": keys.public_key().to_bech32(),
    }))

    loaded = load_or_create_keys(str(key_file))
    assert loaded.public_key().to_bech32() == keys.public_key().to_bech32()


def test_create_keys_when_missing(tmp_path):
    """New keys generated and saved when file doesn't exist."""
    key_file = tmp_path / "subdir" / "key.json"
    assert not key_file.exists()

    keys = load_or_create_keys(str(key_file))
    assert key_file.exists()

    data = json.loads(key_file.read_text())
    assert data["nsec"].startswith("nsec1")
    assert data["npub"].startswith("npub1")
    assert data["npub"] == keys.public_key().to_bech32()


def test_load_keys_roundtrip(tmp_path):
    """Keys survive save-then-load cycle."""
    key_file = tmp_path / "key.json"
    keys1 = load_or_create_keys(str(key_file))
    keys2 = load_or_create_keys(str(key_file))
    assert keys1.public_key().to_bech32() == keys2.public_key().to_bech32()
    assert keys1.secret_key().to_bech32() == keys2.secret_key().to_bech32()
