"""Tests for local_db — contacts, groups, messages."""
import pytest
import local_db as DB


# --- Contacts ---

@pytest.mark.asyncio
async def test_add_and_get_contacts(db):
    await DB.add_contact(db, "npub1abc", "alice")
    await DB.add_contact(db, "npub1def", "bob")
    contacts = await DB.get_contacts(db)
    assert len(contacts) == 2
    assert contacts[0]["nickname"] == "alice"
    assert contacts[1]["nickname"] == "bob"


@pytest.mark.asyncio
async def test_remove_contact(db):
    await DB.add_contact(db, "npub1abc", "alice")
    removed = await DB.remove_contact(db, "alice")
    assert removed is True
    contacts = await DB.get_contacts(db)
    assert len(contacts) == 0


@pytest.mark.asyncio
async def test_remove_nonexistent_contact(db):
    removed = await DB.remove_contact(db, "nobody")
    assert removed is False


@pytest.mark.asyncio
async def test_resolve_name_by_nickname(db):
    await DB.add_contact(db, "npub1abc", "alice")
    npub = await DB.resolve_name(db, "alice")
    assert npub == "npub1abc"


@pytest.mark.asyncio
async def test_resolve_name_by_npub(db):
    npub = await DB.resolve_name(db, "npub1abc")
    assert npub == "npub1abc"


@pytest.mark.asyncio
async def test_resolve_unknown_nickname(db):
    result = await DB.resolve_name(db, "unknown")
    assert result is None


@pytest.mark.asyncio
async def test_get_display_name_with_nickname(db):
    await DB.add_contact(db, "npub1abc", "alice")
    name = await DB.get_display_name(db, "npub1abc")
    assert name == "@alice"


@pytest.mark.asyncio
async def test_get_display_name_without_nickname(db):
    name = await DB.get_display_name(db, "npub1abcdef123456")
    assert name == "npub1abcdef1.."


@pytest.mark.asyncio
async def test_update_contact_nickname(db):
    await DB.add_contact(db, "npub1abc", "alice")
    await DB.add_contact(db, "npub1abc", "alice2")
    contacts = await DB.get_contacts(db)
    assert len(contacts) == 1
    assert contacts[0]["nickname"] == "alice2"


# --- Groups ---

@pytest.mark.asyncio
async def test_create_group(db):
    await DB.create_group(db, "builders", "npub1me")
    assert await DB.group_exists(db, "builders")
    members = await DB.get_members(db, "builders")
    assert "npub1me" in members


@pytest.mark.asyncio
async def test_add_member(db):
    await DB.create_group(db, "builders", "npub1me")
    await DB.add_member(db, "builders", "npub1alice")
    members = await DB.get_members(db, "builders")
    assert "npub1alice" in members
    assert len(members) == 2


@pytest.mark.asyncio
async def test_remove_member(db):
    await DB.create_group(db, "builders", "npub1me")
    await DB.add_member(db, "builders", "npub1alice")
    await DB.remove_member(db, "builders", "npub1alice")
    members = await DB.get_members(db, "builders")
    assert "npub1alice" not in members


@pytest.mark.asyncio
async def test_get_groups(db):
    await DB.create_group(db, "alpha", "npub1me")
    await DB.create_group(db, "beta", "npub1me")
    groups = await DB.get_groups(db)
    assert groups == ["alpha", "beta"]


@pytest.mark.asyncio
async def test_sync_members(db):
    await DB.create_group(db, "team", "npub1me")
    await DB.add_member(db, "team", "npub1old")
    await DB.sync_members(db, "team", ["npub1a", "npub1b", "npub1c"])
    members = await DB.get_members(db, "team")
    assert set(members) == {"npub1a", "npub1b", "npub1c"}


@pytest.mark.asyncio
async def test_sync_members_creates_group(db):
    await DB.sync_members(db, "newgroup", ["npub1a", "npub1b"])
    assert await DB.group_exists(db, "newgroup")
    members = await DB.get_members(db, "newgroup")
    assert set(members) == {"npub1a", "npub1b"}


@pytest.mark.asyncio
async def test_delete_group(db):
    await DB.create_group(db, "temp", "npub1me")
    deleted = await DB.delete_group(db, "temp")
    assert deleted is True
    assert not await DB.group_exists(db, "temp")


# --- Messages ---

@pytest.mark.asyncio
async def test_save_and_get_unread(db):
    await DB.save_message(db, "npub1abc", "hello")
    await DB.save_message(db, "npub1def", "world")
    unread = await DB.get_unread(db)
    assert len(unread) == 2
    assert unread[0]["text"] == "hello"
    assert unread[1]["text"] == "world"


@pytest.mark.asyncio
async def test_mark_all_read(db):
    await DB.save_message(db, "npub1abc", "hello")
    await DB.save_message(db, "npub1def", "world")
    count = await DB.mark_all_read(db)
    assert count == 2
    unread = await DB.get_unread(db)
    assert len(unread) == 0


@pytest.mark.asyncio
async def test_save_group_message(db):
    await DB.save_message(db, "npub1abc", "hello group", is_group=True, group_name="builders")
    unread = await DB.get_unread(db)
    assert len(unread) == 1
    assert unread[0]["is_group"] == 1
    assert unread[0]["group_name"] == "builders"
