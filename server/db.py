import hashlib
import aiosqlite
from typing import Optional

DB_PATH = "server/world.db"


async def init_db(path: str = DB_PATH) -> aiosqlite.Connection:
    db = await aiosqlite.connect(path)
    db.row_factory = aiosqlite.Row
    await db.executescript("""
        CREATE TABLE IF NOT EXISTS agents (
            id TEXT PRIMARY KEY,
            password_hash TEXT NOT NULL,
            room_description TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS room_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id TEXT NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            icon TEXT NOT NULL,
            description TEXT DEFAULT ''
        );

        CREATE UNIQUE INDEX IF NOT EXISTS idx_room_items_owner_name
            ON room_items(owner_id, name);
    """)
    await db.commit()
    return db


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


async def get_agent(db: aiosqlite.Connection, agent_id: str) -> Optional[dict]:
    async with db.execute(
        "SELECT id, password_hash, room_description FROM agents WHERE id = ?",
        (agent_id,)
    ) as cur:
        row = await cur.fetchone()
        return dict(row) if row else None


async def create_agent(db: aiosqlite.Connection, agent_id: str, password_hash: str) -> dict:
    await db.execute(
        "INSERT INTO agents (id, password_hash) VALUES (?, ?)",
        (agent_id, password_hash)
    )
    await db.commit()
    return {"id": agent_id, "password_hash": password_hash, "room_description": ""}


async def update_room_desc(db: aiosqlite.Connection, agent_id: str, desc: str) -> None:
    await db.execute(
        "UPDATE agents SET room_description = ? WHERE id = ?",
        (desc, agent_id)
    )
    await db.commit()


async def add_item(
    db: aiosqlite.Connection, owner_id: str, icon: str, name: str, desc: str
) -> dict:
    cur = await db.execute(
        "INSERT INTO room_items (owner_id, icon, name, description) VALUES (?, ?, ?, ?)",
        (owner_id, icon, name, desc)
    )
    await db.commit()
    return {"id": cur.lastrowid, "icon": icon, "name": name, "description": desc}


async def remove_item(db: aiosqlite.Connection, owner_id: str, name: str) -> bool:
    cur = await db.execute(
        "DELETE FROM room_items WHERE owner_id = ? AND name = ?",
        (owner_id, name)
    )
    await db.commit()
    return cur.rowcount > 0


async def get_room(db: aiosqlite.Connection, owner_id: str) -> dict:
    agent = await get_agent(db, owner_id)
    description = agent["room_description"] if agent else ""
    async with db.execute(
        "SELECT id, icon, name, description FROM room_items WHERE owner_id = ? ORDER BY id",
        (owner_id,)
    ) as cur:
        items = [dict(row) for row in await cur.fetchall()]
    return {"description": description, "items": items}


async def get_item(
    db: aiosqlite.Connection, owner_id: str, item_name: str
) -> Optional[dict]:
    async with db.execute(
        "SELECT id, icon, name, description FROM room_items WHERE owner_id = ? AND name = ?",
        (owner_id, item_name)
    ) as cur:
        row = await cur.fetchone()
        return dict(row) if row else None
