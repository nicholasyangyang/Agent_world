"""Shared fixtures for Agent World tests."""
import pytest
from unittest.mock import AsyncMock, MagicMock

import local_db as DB
from client.gateway import GatewayState


@pytest.fixture
async def db():
    """In-memory SQLite database."""
    conn = await DB.init_db(":memory:")
    yield conn
    await conn.close()


@pytest.fixture
async def state():
    """GatewayState with in-memory DB and mocked Nostr client."""
    conn = await DB.init_db(":memory:")
    nostr = MagicMock()
    nostr.send_dm = AsyncMock()
    own_npub = "npub1ownkey123456789"
    s = GatewayState(nostr, conn, own_npub)
    s._connected_relays = ["wss://relay.test"]
    yield s
    await conn.close()
