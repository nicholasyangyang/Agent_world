"""Local SQLite database for contacts, groups, and messages."""
import aiosqlite
from typing import Optional


async def init_db(path: str = "contacts.db") -> aiosqlite.Connection:
    db = await aiosqlite.connect(path)
    db.row_factory = aiosqlite.Row
    await db.executescript("""
        CREATE TABLE IF NOT EXISTS contacts (
            npub TEXT PRIMARY KEY,
            nickname TEXT UNIQUE NOT NULL
        );

        CREATE TABLE IF NOT EXISTS groups_ (
            name TEXT PRIMARY KEY,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS group_members (
            group_name TEXT NOT NULL REFERENCES groups_(name) ON DELETE CASCADE,
            npub TEXT NOT NULL,
            PRIMARY KEY (group_name, npub)
        );

        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            from_npub TEXT NOT NULL,
            text TEXT NOT NULL,
            is_group INTEGER DEFAULT 0,
            group_name TEXT,
            received_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            read INTEGER DEFAULT 0
        );
    """)
    await db.commit()
    return db


# --- Contacts ---

async def add_contact(db: aiosqlite.Connection, npub: str, nickname: str) -> None:
    await db.execute(
        "INSERT OR REPLACE INTO contacts (npub, nickname) VALUES (?, ?)",
        (npub, nickname)
    )
    await db.commit()


async def remove_contact(db: aiosqlite.Connection, nickname: str) -> bool:
    cur = await db.execute("DELETE FROM contacts WHERE nickname = ?", (nickname,))
    await db.commit()
    return cur.rowcount > 0


async def get_contacts(db: aiosqlite.Connection) -> list[dict]:
    async with db.execute("SELECT npub, nickname FROM contacts ORDER BY nickname") as cur:
        return [dict(row) for row in await cur.fetchall()]


async def resolve_name(db: aiosqlite.Connection, name: str) -> Optional[str]:
    """Resolve a nickname to npub. Returns npub if name starts with 'npub1'."""
    if name.startswith("npub1"):
        return name
    async with db.execute(
        "SELECT npub FROM contacts WHERE nickname = ?", (name,)
    ) as cur:
        row = await cur.fetchone()
        return row["npub"] if row else None


async def get_display_name(db: aiosqlite.Connection, npub: str) -> str:
    """Get nickname for npub, or npub short form (first 8 chars + ..)."""
    async with db.execute(
        "SELECT nickname FROM contacts WHERE npub = ?", (npub,)
    ) as cur:
        row = await cur.fetchone()
        if row:
            return f"@{row['nickname']}"
    return npub[:12] + ".."


# --- Groups ---

async def create_group(db: aiosqlite.Connection, name: str, own_npub: str) -> None:
    await db.execute("INSERT INTO groups_ (name) VALUES (?)", (name,))
    await db.execute(
        "INSERT INTO group_members (group_name, npub) VALUES (?, ?)",
        (name, own_npub)
    )
    await db.commit()


async def delete_group(db: aiosqlite.Connection, name: str) -> bool:
    cur = await db.execute("DELETE FROM groups_ WHERE name = ?", (name,))
    await db.commit()
    return cur.rowcount > 0


async def get_groups(db: aiosqlite.Connection) -> list[str]:
    async with db.execute("SELECT name FROM groups_ ORDER BY name") as cur:
        return [row["name"] for row in await cur.fetchall()]


async def add_member(db: aiosqlite.Connection, group_name: str, npub: str) -> None:
    await db.execute(
        "INSERT OR IGNORE INTO group_members (group_name, npub) VALUES (?, ?)",
        (group_name, npub)
    )
    await db.commit()


async def remove_member(db: aiosqlite.Connection, group_name: str, npub: str) -> None:
    await db.execute(
        "DELETE FROM group_members WHERE group_name = ? AND npub = ?",
        (group_name, npub)
    )
    await db.commit()


async def get_members(db: aiosqlite.Connection, group_name: str) -> list[str]:
    async with db.execute(
        "SELECT npub FROM group_members WHERE group_name = ? ORDER BY npub",
        (group_name,)
    ) as cur:
        return [row["npub"] for row in await cur.fetchall()]


async def group_exists(db: aiosqlite.Connection, name: str) -> bool:
    async with db.execute("SELECT 1 FROM groups_ WHERE name = ?", (name,)) as cur:
        return await cur.fetchone() is not None


async def sync_members(
    db: aiosqlite.Connection, group_name: str, members: list[str]
) -> None:
    """Replace all members of a group with the given list."""
    if not await group_exists(db, group_name):
        await db.execute("INSERT INTO groups_ (name) VALUES (?)", (group_name,))
    await db.execute(
        "DELETE FROM group_members WHERE group_name = ?", (group_name,)
    )
    for npub in members:
        await db.execute(
            "INSERT INTO group_members (group_name, npub) VALUES (?, ?)",
            (group_name, npub)
        )
    await db.commit()


# --- Messages ---

async def save_message(
    db: aiosqlite.Connection, from_npub: str, text: str,
    is_group: bool = False, group_name: str = None
) -> None:
    await db.execute(
        "INSERT INTO messages (from_npub, text, is_group, group_name) VALUES (?, ?, ?, ?)",
        (from_npub, text, int(is_group), group_name)
    )
    await db.commit()


async def get_unread(db: aiosqlite.Connection) -> list[dict]:
    async with db.execute(
        "SELECT id, from_npub, text, is_group, group_name, received_at "
        "FROM messages WHERE read = 0 ORDER BY received_at"
    ) as cur:
        return [dict(row) for row in await cur.fetchall()]


async def mark_all_read(db: aiosqlite.Connection) -> int:
    cur = await db.execute("UPDATE messages SET read = 1 WHERE read = 0")
    await db.commit()
    return cur.rowcount
