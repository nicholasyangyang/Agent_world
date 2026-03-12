"""Tests for group protocol message handling (incoming NIP-17 DMs)."""
import pytest
from unittest.mock import AsyncMock, MagicMock

import local_db as DB
from client.gateway import GatewayState, handle_incoming_dm, handle_group_message


@pytest.fixture
async def state():
    db = await DB.init_db(":memory:")
    nostr = MagicMock()
    nostr.send_dm = AsyncMock()
    own_npub = "npub1me"
    s = GatewayState(nostr, db, own_npub)
    yield s
    await db.close()


# --- Plain DM handling ---

@pytest.mark.asyncio
async def test_incoming_plain_dm(state):
    await handle_incoming_dm(state, "npub1abc", "hello world")
    assert state._msg_count == 1
    assert len(state.message_queue) == 1
    assert state.message_queue[0]["type"] == "dm"
    assert state.message_queue[0]["text"] == "hello world"
    unread = await DB.get_unread(state.db)
    assert len(unread) == 1


@pytest.mark.asyncio
async def test_incoming_invalid_json_treated_as_dm(state):
    await handle_incoming_dm(state, "npub1abc", "{bad json")
    assert state._msg_count == 1
    assert state.message_queue[0]["type"] == "dm"


@pytest.mark.asyncio
async def test_incoming_json_without_type_treated_as_dm(state):
    await handle_incoming_dm(state, "npub1abc", '{"data": 123}')
    assert state.message_queue[0]["type"] == "dm"


# --- Group invite ---

@pytest.mark.asyncio
async def test_group_invite_received(state):
    data = {"type": "group_invite", "group": "team", "from_npub": "npub1inviter"}
    await handle_group_message(state, "npub1inviter", data)
    assert len(state.message_queue) == 1
    assert state.message_queue[0]["type"] == "group_invite"
    assert state.message_queue[0]["group"] == "team"


# --- Group accept ---

@pytest.mark.asyncio
async def test_group_accept_adds_member(state):
    await DB.create_group(state.db, "team", state.own_npub)
    data = {"type": "group_accept", "group": "team", "from_npub": "npub1alice"}
    await handle_group_message(state, "npub1alice", data)
    members = await DB.get_members(state.db, "team")
    assert "npub1alice" in members
    assert state.message_queue[0]["type"] == "group_accept"


@pytest.mark.asyncio
async def test_group_accept_broadcasts_sync(state):
    await DB.create_group(state.db, "team", state.own_npub)
    await DB.add_member(state.db, "team", "npub1bob")
    data = {"type": "group_accept", "group": "team", "from_npub": "npub1alice"}
    await handle_group_message(state, "npub1alice", data)
    # Should sync to npub1bob (not own_npub, not npub1alice)
    assert state.nostr.send_dm.await_count == 1
    call_args = state.nostr.send_dm.call_args
    assert call_args[0][0] == "npub1bob"


@pytest.mark.asyncio
async def test_group_accept_nonexistent_group_ignored(state):
    data = {"type": "group_accept", "group": "nope", "from_npub": "npub1alice"}
    await handle_group_message(state, "npub1alice", data)
    assert len(state.message_queue) == 0


# --- Members sync ---

@pytest.mark.asyncio
async def test_group_members_sync(state):
    data = {
        "type": "group_members_sync", "group": "team",
        "members": ["npub1a", "npub1b", "npub1c"]
    }
    await handle_group_message(state, "npub1someone", data)
    assert await DB.group_exists(state.db, "team")
    members = await DB.get_members(state.db, "team")
    assert set(members) == {"npub1a", "npub1b", "npub1c"}
    assert state.message_queue[0]["type"] == "group_members_sync"


# --- Group position ---

@pytest.mark.asyncio
async def test_group_position_forwarded(state):
    import asyncio
    # Create a mock subscriber
    mock_writer = MagicMock()
    mock_writer.write = MagicMock()
    mock_writer.drain = AsyncMock()
    state.group_subscribers["team"] = [mock_writer]

    data = {"type": "group_position", "group": "team", "from_npub": "npub1alice", "x": 5, "y": 3}
    await handle_group_message(state, "npub1alice", data)
    mock_writer.write.assert_called_once()
    written = mock_writer.write.call_args[0][0].decode()
    import json
    event = json.loads(written.strip())
    assert event["type"] == "position"
    assert event["x"] == 5
    assert event["y"] == 3


# --- Group leave ---

@pytest.mark.asyncio
async def test_group_leave_removes_member(state):
    await DB.create_group(state.db, "team", state.own_npub)
    await DB.add_member(state.db, "team", "npub1alice")
    data = {"type": "group_leave", "group": "team", "from_npub": "npub1alice"}
    await handle_group_message(state, "npub1alice", data)
    members = await DB.get_members(state.db, "team")
    assert "npub1alice" not in members
    assert state.message_queue[0]["type"] == "group_leave"


@pytest.mark.asyncio
async def test_group_leave_nonexistent_group(state):
    data = {"type": "group_leave", "group": "nope", "from_npub": "npub1alice"}
    await handle_group_message(state, "npub1alice", data)
    # Should still queue the notification
    assert state.message_queue[0]["type"] == "group_leave"
