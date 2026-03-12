"""Tests for gateway IPC command handling (mocked Nostr layer)."""
import asyncio
import pytest
from unittest.mock import AsyncMock

import local_db as DB
from client.gateway import handle_ipc_cmd


# --- Basic commands ---

@pytest.mark.asyncio
async def test_whoami(state):
    res = await handle_ipc_cmd("whoami", {}, state)
    assert res["ok"] is True
    assert res["output"] == state.own_npub


@pytest.mark.asyncio
async def test_status(state):
    res = await handle_ipc_cmd("status", {}, state)
    assert res["ok"] is True
    assert "npub1ownkey" in res["output"]
    assert "1 connected" in res["output"]


@pytest.mark.asyncio
async def test_stop(state):
    res = await handle_ipc_cmd("stop", {}, state)
    assert res["ok"] is True
    assert state._shutdown.is_set()


@pytest.mark.asyncio
async def test_unknown_cmd(state):
    res = await handle_ipc_cmd("nonsense", {}, state)
    assert res["ok"] is False
    assert "未知命令" in res["output"]


# --- Contacts ---

@pytest.mark.asyncio
async def test_add_and_list_contacts(state):
    res = await handle_ipc_cmd("add_contact", {"npub": "npub1abc", "nickname": "alice"}, state)
    assert res["ok"] is True
    res = await handle_ipc_cmd("contacts", {}, state)
    assert "@alice" in res["output"]


@pytest.mark.asyncio
async def test_add_contact_invalid(state):
    res = await handle_ipc_cmd("add_contact", {"npub": "badkey", "nickname": "alice"}, state)
    assert res["ok"] is False


@pytest.mark.asyncio
async def test_rm_contact(state):
    await handle_ipc_cmd("add_contact", {"npub": "npub1abc", "nickname": "alice"}, state)
    res = await handle_ipc_cmd("rm_contact", {"nickname": "alice"}, state)
    assert res["ok"] is True
    res = await handle_ipc_cmd("contacts", {}, state)
    assert "暂无联系人" in res["output"]


@pytest.mark.asyncio
async def test_rm_nonexistent_contact(state):
    res = await handle_ipc_cmd("rm_contact", {"nickname": "nobody"}, state)
    assert res["ok"] is False


# --- Messaging ---

@pytest.mark.asyncio
async def test_msg_by_npub(state):
    res = await handle_ipc_cmd("msg", {"target": "npub1abc", "text": "hello"}, state)
    assert res["ok"] is True
    await asyncio.sleep(0)  # let background task run
    state.nostr.send_dm.assert_called_once_with("npub1abc", "hello")


@pytest.mark.asyncio
async def test_msg_by_nickname(state):
    await DB.add_contact(state.db, "npub1xyz", "bob")
    res = await handle_ipc_cmd("msg", {"target": "bob", "text": "hi bob"}, state)
    assert res["ok"] is True
    await asyncio.sleep(0)
    state.nostr.send_dm.assert_called_once_with("npub1xyz", "hi bob")


@pytest.mark.asyncio
async def test_msg_unknown_target(state):
    res = await handle_ipc_cmd("msg", {"target": "nobody", "text": "hi"}, state)
    assert res["ok"] is False


@pytest.mark.asyncio
async def test_msg_fire_and_forget(state):
    """msg returns immediately, send_dm runs in background."""
    res = await handle_ipc_cmd("msg", {"target": "npub1abc", "text": "hi"}, state)
    assert res["ok"] is True
    # Response returned before send_dm completes
    assert "已发送" in res["output"]


# --- Inbox ---

@pytest.mark.asyncio
async def test_inbox_empty(state):
    res = await handle_ipc_cmd("inbox", {}, state)
    assert res["ok"] is True
    assert res["messages"] == []
    assert res["notifications"] == []


@pytest.mark.asyncio
async def test_inbox_with_messages(state):
    await DB.save_message(state.db, "npub1abc", "hello")
    state.message_queue.append({"type": "group_invite", "group": "team", "from": "npub1abc"})
    res = await handle_ipc_cmd("inbox", {}, state)
    assert len(res["messages"]) == 1
    assert len(res["notifications"]) == 1
    # Queue drained
    assert len(state.message_queue) == 0


# --- Groups ---

@pytest.mark.asyncio
async def test_group_create(state):
    res = await handle_ipc_cmd("group_create", {"name": "builders"}, state)
    assert res["ok"] is True
    assert await DB.group_exists(state.db, "builders")


@pytest.mark.asyncio
async def test_group_create_duplicate(state):
    await handle_ipc_cmd("group_create", {"name": "builders"}, state)
    res = await handle_ipc_cmd("group_create", {"name": "builders"}, state)
    assert res["ok"] is False


@pytest.mark.asyncio
async def test_group_list(state):
    await handle_ipc_cmd("group_create", {"name": "alpha"}, state)
    await handle_ipc_cmd("group_create", {"name": "beta"}, state)
    res = await handle_ipc_cmd("groups", {}, state)
    assert "alpha" in res["output"]
    assert "beta" in res["output"]


@pytest.mark.asyncio
async def test_group_list_empty(state):
    res = await handle_ipc_cmd("groups", {}, state)
    assert "暂无群组" in res["output"]


@pytest.mark.asyncio
async def test_group_invite(state):
    await handle_ipc_cmd("group_create", {"name": "team"}, state)
    await DB.add_contact(state.db, "npub1alice", "alice")
    res = await handle_ipc_cmd("group_invite", {"group": "team", "nickname": "alice"}, state)
    assert res["ok"] is True
    await asyncio.sleep(0)
    state.nostr.send_dm.assert_called_once()


@pytest.mark.asyncio
async def test_group_invite_unknown_contact(state):
    await handle_ipc_cmd("group_create", {"name": "team"}, state)
    res = await handle_ipc_cmd("group_invite", {"group": "team", "nickname": "nobody"}, state)
    assert res["ok"] is False


@pytest.mark.asyncio
async def test_group_invite_nonexistent_group(state):
    await DB.add_contact(state.db, "npub1alice", "alice")
    res = await handle_ipc_cmd("group_invite", {"group": "nope", "nickname": "alice"}, state)
    assert res["ok"] is False


@pytest.mark.asyncio
async def test_group_join(state):
    res = await handle_ipc_cmd("group_join", {"npub": "npub1inviter", "group": "team"}, state)
    assert res["ok"] is True
    assert await DB.group_exists(state.db, "team")
    await asyncio.sleep(0)
    state.nostr.send_dm.assert_called_once()


@pytest.mark.asyncio
async def test_group_members(state):
    await handle_ipc_cmd("group_create", {"name": "team"}, state)
    res = await handle_ipc_cmd("group_members", {"group": "team"}, state)
    assert res["ok"] is True
    assert "(你)" in res["output"]


@pytest.mark.asyncio
async def test_group_members_nonexistent(state):
    res = await handle_ipc_cmd("group_members", {"group": "nope"}, state)
    assert res["ok"] is False


@pytest.mark.asyncio
async def test_group_leave(state):
    await handle_ipc_cmd("group_create", {"name": "team"}, state)
    await DB.add_member(state.db, "team", "npub1alice")
    res = await handle_ipc_cmd("group_leave", {"group": "team"}, state)
    assert res["ok"] is True
    assert not await DB.group_exists(state.db, "team")
    await asyncio.sleep(0)
    state.nostr.send_dm.assert_called_once()


@pytest.mark.asyncio
async def test_group_position(state):
    await handle_ipc_cmd("group_create", {"name": "team"}, state)
    await DB.add_member(state.db, "team", "npub1alice")
    res = await handle_ipc_cmd("group_position", {"group": "team", "x": 5, "y": 3}, state)
    assert res["ok"] is True
    await asyncio.sleep(0)
    state.nostr.send_dm.assert_called_once()


@pytest.mark.asyncio
async def test_group_position_nonexistent(state):
    res = await handle_ipc_cmd("group_position", {"group": "nope", "x": 0, "y": 0}, state)
    assert res["ok"] is False
