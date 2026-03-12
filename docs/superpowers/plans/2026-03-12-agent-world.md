# Agent World Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a multi-player real-time interaction system where humans/AI agents each have rooms, can place items, visit each other, and chat via WebSocket.

**Architecture:** Three-layer model: central WebSocket server (port 8765) with SQLite persistence, local gateway daemon maintaining server connection + UDS IPC at `~/.agent/sock`, and single-shot CLI commands. Server handles all game logic; gateway caches push messages for CLI retrieval.

**Tech Stack:** Python 3.11+, websockets>=12.0, aiosqlite>=0.19.0, click>=8.0, pytest + pytest-asyncio

---

## Chunk 1: Project Scaffold + Protocol + DB

### Task 1: Project Scaffold

**Files:**
- Create: `requirements.txt`
- Create: `pyproject.toml`
- Create: `protocol.py`
- Create: `server/__init__.py`
- Create: `client/__init__.py`
- Create: `tests/__init__.py`

- [ ] **Step 1: Create requirements.txt**

```
websockets>=12.0
aiosqlite>=0.19.0
click>=8.0
pytest>=8.0
pytest-asyncio>=0.23.0
```

- [ ] **Step 2: Create pyproject.toml**

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
```

- [ ] **Step 3: Create protocol.py with all message type constants**

```python
# Message types: Client→Server
AUTH = "AUTH"
SET_DESC = "SET_DESC"
PLACE_ITEM = "PLACE_ITEM"
REMOVE_ITEM = "REMOVE_ITEM"
LOOK = "LOOK"
WHO = "WHO"
LIST = "LIST"
KNOCK = "KNOCK"
KNOCK_REPLY = "KNOCK_REPLY"
ENTER = "ENTER"
SAY = "SAY"
WHISPER = "WHISPER"
HOME = "HOME"

# Message types: Server→Client
AUTH_OK = "AUTH_OK"
AUTH_FAIL = "AUTH_FAIL"
DESC_UPDATED = "DESC_UPDATED"
ITEM_PLACED = "ITEM_PLACED"
ITEM_REMOVED = "ITEM_REMOVED"
LOOK_RESULT = "LOOK_RESULT"
WHO_RESULT = "WHO_RESULT"
LIST_RESULT = "LIST_RESULT"
KNOCK_RECEIVED = "KNOCK_RECEIVED"
KNOCK_ACCEPTED = "KNOCK_ACCEPTED"
KNOCK_REJECTED = "KNOCK_REJECTED"
ENTER_OK = "ENTER_OK"
VISITOR_JOINED = "VISITOR_JOINED"
VISITOR_LEFT = "VISITOR_LEFT"
SAID = "SAID"
WHISPERED = "WHISPERED"
HOME_OK = "HOME_OK"
ERROR = "ERROR"

# Gateway push types (not forwarded to pending_response)
PUSH_TYPES = {
    SAID, WHISPERED, KNOCK_RECEIVED, KNOCK_ACCEPTED, KNOCK_REJECTED,
    VISITOR_JOINED, VISITOR_LEFT,
}

# Gateway response types (forwarded to pending_response)
RESPONSE_TYPES = {
    AUTH_OK, AUTH_FAIL, DESC_UPDATED, ITEM_PLACED, ITEM_REMOVED,
    LOOK_RESULT, WHO_RESULT, LIST_RESULT, ENTER_OK, HOME_OK, ERROR,
}
```

- [ ] **Step 4: Create empty __init__.py files**

```bash
touch server/__init__.py client/__init__.py tests/__init__.py
```

- [ ] **Step 5: Install dependencies**

```bash
cd /home/deeptuuk/OnlyCC/Agent_world && pip install -r requirements.txt -q
```

- [ ] **Step 6: Commit**

```bash
git init
git add requirements.txt pyproject.toml protocol.py server/__init__.py client/__init__.py tests/__init__.py
git commit -m "feat: scaffold project with protocol constants"
```

---

### Task 2: Database Layer

**Files:**
- Create: `server/db.py`

- [ ] **Step 1: Write server/db.py**

```python
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
```

- [ ] **Step 2: Commit**

```bash
git add server/db.py
git commit -m "feat: add database layer with SQLite/aiosqlite"
```

---

## Chunk 2: Server Core (AUTH + LOOK)

### Task 3: Server State + Handlers Skeleton

**Files:**
- Create: `server/handlers.py`
- Create: `server/main.py`

- [ ] **Step 1: Write server/handlers.py (AUTH + LOOK)**

```python
import json
import logging
from types import SimpleNamespace
from typing import Any
import websockets

import protocol as P
from server import db as DB

logger = logging.getLogger(__name__)


async def send_msg(ws, msg: dict) -> None:
    await ws.send(json.dumps(msg))


async def send_error(ws, reason: str) -> None:
    await send_msg(ws, {"type": P.ERROR, "reason": reason})


async def broadcast_to_room(
    state: SimpleNamespace, room_owner_id: str, msg: dict, exclude: str = None
) -> None:
    for aid, loc in list(state.locations.items()):
        actual_room = loc if loc else aid
        if actual_room == room_owner_id and aid != exclude:
            if aid in state.connections:
                try:
                    await state.connections[aid].send(json.dumps(msg))
                except Exception:
                    pass


def current_room(state: SimpleNamespace, agent_id: str) -> str:
    loc = state.locations.get(agent_id)
    return loc if loc else agent_id


def is_in_own_room(state: SimpleNamespace, agent_id: str) -> bool:
    return state.locations.get(agent_id) is None


async def handle_auth(ws, msg: dict, state: SimpleNamespace) -> str | None:
    name = msg.get("name", "").strip()
    password = msg.get("password", "")
    if not name or not password:
        await send_msg(ws, {"type": P.AUTH_FAIL, "reason": "name and password required"})
        return None
    if name in state.connections:
        await send_msg(ws, {"type": P.AUTH_FAIL, "reason": "already online"})
        return None
    agent = await DB.get_agent(state.db, name)
    pw_hash = DB.hash_password(password)
    if agent is None:
        agent = await DB.create_agent(state.db, name, pw_hash)
        logger.info("Registered new agent: %s", name)
    elif agent["password_hash"] != pw_hash:
        await send_msg(ws, {"type": P.AUTH_FAIL, "reason": "wrong password"})
        return None
    state.connections[name] = ws
    state.locations[name] = None  # own room
    room_data = await DB.get_room(state.db, name)
    room_data["visitors"] = [
        aid for aid, loc in state.locations.items() if loc == name
    ]
    await send_msg(ws, {"type": P.AUTH_OK, "agent_id": name, "room": room_data})
    logger.info("Agent authenticated: %s", name)
    return name


async def handle_look(ws, msg: dict, agent_id: str, state: SimpleNamespace) -> None:
    item_name = msg.get("item_name")
    room_owner = current_room(state, agent_id)
    if item_name:
        item = await DB.get_item(state.db, room_owner, item_name)
        if item is None:
            await send_error(ws, f"物品 '{item_name}' 不存在")
            return
        await send_msg(ws, {"type": P.LOOK_RESULT, "item": item})
    else:
        room_data = await DB.get_room(state.db, room_owner)
        room_data["owner"] = room_owner
        room_data["visitors"] = [
            aid for aid, loc in state.locations.items() if loc == room_owner
        ]
        await send_msg(ws, {"type": P.LOOK_RESULT, "room": room_data})


async def handle_set_desc(ws, msg: dict, agent_id: str, state: SimpleNamespace) -> None:
    if not is_in_own_room(state, agent_id):
        await send_error(ws, "只能在自己房间修改描述")
        return
    desc = msg.get("description", "")
    await DB.update_room_desc(state.db, agent_id, desc)
    await send_msg(ws, {"type": P.DESC_UPDATED})


async def handle_place_item(ws, msg: dict, agent_id: str, state: SimpleNamespace) -> None:
    if not is_in_own_room(state, agent_id):
        await send_error(ws, "只能在自己房间放置物品")
        return
    icon = msg.get("icon", "")
    name = msg.get("name", "").strip()
    desc = msg.get("description", "")
    if not icon or not name:
        await send_error(ws, "icon 和 name 不能为空")
        return
    try:
        item = await DB.add_item(state.db, agent_id, icon, name, desc)
    except Exception:
        await send_error(ws, f"物品 '{name}' 已存在")
        return
    await send_msg(ws, {"type": P.ITEM_PLACED, "item": item})


async def handle_remove_item(ws, msg: dict, agent_id: str, state: SimpleNamespace) -> None:
    if not is_in_own_room(state, agent_id):
        await send_error(ws, "只能在自己房间移除物品")
        return
    name = msg.get("name", "").strip()
    if not name:
        await send_error(ws, "name 不能为空")
        return
    removed = await DB.remove_item(state.db, agent_id, name)
    if not removed:
        await send_error(ws, f"物品 '{name}' 不存在")
        return
    await send_msg(ws, {"type": P.ITEM_REMOVED, "name": name})


async def handle_who(ws, msg: dict, agent_id: str, state: SimpleNamespace) -> None:
    room_owner = current_room(state, agent_id)
    visitors = [aid for aid, loc in state.locations.items() if loc == room_owner]
    await send_msg(ws, {"type": P.WHO_RESULT, "room": room_owner, "visitors": visitors})


async def handle_list(ws, msg: dict, agent_id: str, state: SimpleNamespace) -> None:
    online = list(state.connections.keys())
    await send_msg(ws, {"type": P.LIST_RESULT, "agents": online})


async def handle_knock(ws, msg: dict, agent_id: str, state: SimpleNamespace) -> None:
    target = msg.get("target", "").strip()
    if not target:
        await send_error(ws, "target 不能为空")
        return
    if target not in state.connections:
        await send_error(ws, "目标玩家不在线")
        return
    if state.locations.get(target) is not None:
        await send_error(ws, "目标玩家不在自己房间")
        return
    if target not in state.pending_knocks:
        state.pending_knocks[target] = set()
    state.pending_knocks[target].add(agent_id)
    target_ws = state.connections[target]
    await send_msg(target_ws, {"type": P.KNOCK_RECEIVED, "from": agent_id})


async def handle_knock_reply(ws, msg: dict, agent_id: str, state: SimpleNamespace) -> None:
    if not is_in_own_room(state, agent_id):
        await send_error(ws, "只能在自己房间回应来访")
        return
    requester = msg.get("to", "").strip()
    accept = msg.get("accept", False)
    knocks = state.pending_knocks.get(agent_id, set())
    if requester not in knocks:
        await send_error(ws, "没有该用户的来访请求")
        return
    knocks.discard(requester)
    if requester not in state.connections:
        return  # requester disconnected
    req_ws = state.connections[requester]
    if accept:
        if agent_id not in state.accepted_knocks:
            state.accepted_knocks[agent_id] = set()
        state.accepted_knocks[agent_id].add(requester)
        await send_msg(req_ws, {"type": P.KNOCK_ACCEPTED, "from": agent_id})
    else:
        await send_msg(req_ws, {"type": P.KNOCK_REJECTED, "from": agent_id})


async def handle_enter(ws, msg: dict, agent_id: str, state: SimpleNamespace) -> None:
    target = msg.get("target", "").strip()
    if not target:
        await send_error(ws, "target 不能为空")
        return
    accepted = state.accepted_knocks.get(target, set())
    if agent_id not in accepted:
        await send_error(ws, "未被接受，无法进入")
        return
    accepted.discard(agent_id)
    # Leave current room
    old_room = current_room(state, agent_id)
    if old_room != agent_id:
        state.locations[agent_id] = None
        await broadcast_to_room(
            state, old_room,
            {"type": P.VISITOR_LEFT, "agent": agent_id, "room": old_room},
            exclude=agent_id
        )
    state.locations[agent_id] = target
    room_data = await DB.get_room(state.db, target)
    room_data["owner"] = target
    room_data["visitors"] = [
        aid for aid, loc in state.locations.items() if loc == target
    ]
    await send_msg(ws, {"type": P.ENTER_OK, "room": room_data})
    await broadcast_to_room(
        state, target,
        {"type": P.VISITOR_JOINED, "agent": agent_id, "room": target},
        exclude=agent_id
    )


async def handle_say(ws, msg: dict, agent_id: str, state: SimpleNamespace) -> None:
    text = msg.get("text", "").strip()
    if not text:
        await send_error(ws, "text 不能为空")
        return
    room_owner = current_room(state, agent_id)
    await broadcast_to_room(
        state, room_owner,
        {"type": P.SAID, "from": agent_id, "text": text, "room": room_owner}
    )


async def handle_whisper(ws, msg: dict, agent_id: str, state: SimpleNamespace) -> None:
    target = msg.get("target", "").strip()
    text = msg.get("text", "").strip()
    if not target or not text:
        await send_error(ws, "target 和 text 不能为空")
        return
    if target not in state.connections:
        await send_error(ws, "目标玩家不在线")
        return
    target_ws = state.connections[target]
    await send_msg(target_ws, {"type": P.WHISPERED, "from": agent_id, "text": text})


async def handle_home(ws, msg: dict, agent_id: str, state: SimpleNamespace) -> None:
    old_room = current_room(state, agent_id)
    if old_room != agent_id:
        state.locations[agent_id] = None
        await broadcast_to_room(
            state, old_room,
            {"type": P.VISITOR_LEFT, "agent": agent_id, "room": old_room},
            exclude=agent_id
        )
    room_data = await DB.get_room(state.db, agent_id)
    room_data["owner"] = agent_id
    room_data["visitors"] = []
    await send_msg(ws, {"type": P.HOME_OK, "room": room_data})


async def dispatch(ws, msg: dict, agent_id: str, state: SimpleNamespace) -> None:
    msg_type = msg.get("type")
    handlers = {
        P.SET_DESC: handle_set_desc,
        P.PLACE_ITEM: handle_place_item,
        P.REMOVE_ITEM: handle_remove_item,
        P.LOOK: handle_look,
        P.WHO: handle_who,
        P.LIST: handle_list,
        P.KNOCK: handle_knock,
        P.KNOCK_REPLY: handle_knock_reply,
        P.ENTER: handle_enter,
        P.SAY: handle_say,
        P.WHISPER: handle_whisper,
        P.HOME: handle_home,
    }
    handler = handlers.get(msg_type)
    if handler:
        await handler(ws, msg, agent_id, state)
    else:
        await send_error(ws, f"未知消息类型: {msg_type}")
```

- [ ] **Step 2: Write server/main.py**

```python
import asyncio
import json
import logging
import signal
import sys
from types import SimpleNamespace

import websockets

import protocol as P
from server import db as DB
from server.handlers import handle_auth, dispatch

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

HOST = "0.0.0.0"
PORT = 8765


def make_state(database) -> SimpleNamespace:
    return SimpleNamespace(
        db=database,
        connections={},
        locations={},
        pending_knocks={},
        accepted_knocks={},
    )


async def on_connect(ws, state: SimpleNamespace) -> None:
    agent_id = None
    try:
        raw = await asyncio.wait_for(ws.recv(), timeout=10.0)
        msg = json.loads(raw)
        if msg.get("type") != P.AUTH:
            await ws.close()
            return
        agent_id = await handle_auth(ws, msg, state)
        if agent_id is None:
            return
        async for raw in ws:
            msg = json.loads(raw)
            await dispatch(ws, msg, agent_id, state)
    except (websockets.exceptions.ConnectionClosed, asyncio.TimeoutError):
        pass
    except json.JSONDecodeError:
        pass
    finally:
        if agent_id and agent_id in state.connections:
            del state.connections[agent_id]
            old_room = state.locations.pop(agent_id, None)
            if old_room:
                from server.handlers import broadcast_to_room
                await broadcast_to_room(
                    state, old_room,
                    {"type": P.VISITOR_LEFT, "agent": agent_id, "room": old_room}
                )
            logger.info("Agent disconnected: %s", agent_id)


async def create_server(database, host: str = HOST, port: int = PORT):
    state = make_state(database)

    async def handler(ws):
        await on_connect(ws, state)

    server = await websockets.serve(handler, host, port)
    return state, server


async def main() -> None:
    database = await DB.init_db()
    state, server = await create_server(database)
    logger.info("Server started on %s:%d", HOST, PORT)

    loop = asyncio.get_running_loop()
    stop = loop.create_future()

    def _handle_signal():
        stop.set_result(None)

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _handle_signal)

    await stop
    server.close()
    await server.wait_closed()
    await database.close()
    logger.info("Server stopped.")


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 3: Commit**

```bash
git add server/handlers.py server/main.py
git commit -m "feat: add server handlers and main entry point"
```

---

## Chunk 3: Tests — conftest + AUTH

### Task 4: Test Infrastructure

**Files:**
- Create: `tests/conftest.py`

- [ ] **Step 1: Write tests/conftest.py**

```python
import asyncio
import json
import pytest
import websockets
from server.db import init_db
from server.main import create_server


@pytest.fixture
async def server():
    db = await init_db(":memory:")
    state, ws_server = await create_server(db, host="127.0.0.1", port=0)
    port = ws_server.sockets[0].getsockname()[1]
    yield {"port": port, "state": state, "db": db}
    ws_server.close()
    await ws_server.wait_closed()
    await db.close()


@pytest.fixture
async def client(server):
    clients = []

    async def make_client(name="testuser", password="testpass"):
        ws = await websockets.connect(f"ws://127.0.0.1:{server['port']}")
        await ws.send(json.dumps({"type": "AUTH", "name": name, "password": password}))
        resp = json.loads(await ws.recv())
        assert resp["type"] == "AUTH_OK"
        clients.append(ws)
        return ws

    yield make_client

    for ws in clients:
        if not ws.closed:
            await ws.close()


async def send(ws, msg: dict) -> dict:
    await ws.send(json.dumps(msg))
    return json.loads(await ws.recv())


async def recv_type(ws, expected_type: str, timeout: float = 2.0) -> dict:
    deadline = asyncio.get_event_loop().time() + timeout
    while True:
        remaining = deadline - asyncio.get_event_loop().time()
        if remaining <= 0:
            raise TimeoutError(f"未收到 {expected_type}")
        raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
        msg = json.loads(raw)
        if msg["type"] == expected_type:
            return msg
```

- [ ] **Step 2: Commit**

```bash
git add tests/conftest.py
git commit -m "test: add shared fixtures for server testing"
```

---

### Task 5: AUTH Tests

**Files:**
- Create: `tests/test_auth.py`

- [ ] **Step 1: Write tests/test_auth.py**

```python
import asyncio
import json
import pytest
import websockets
from tests.conftest import send, recv_type


async def raw_connect(server):
    return await websockets.connect(f"ws://127.0.0.1:{server['port']}")


async def auth(ws, name, password):
    return await send(ws, {"type": "AUTH", "name": name, "password": password})


@pytest.mark.asyncio
async def test_register_new_agent(server):
    ws = await raw_connect(server)
    resp = await auth(ws, "alice", "pass123")
    assert resp["type"] == "AUTH_OK"
    assert resp["agent_id"] == "alice"
    assert "room" in resp
    assert resp["room"]["items"] == []
    await ws.close()


@pytest.mark.asyncio
async def test_login_existing_agent(server):
    ws1 = await raw_connect(server)
    await auth(ws1, "alice", "pass123")
    await ws1.close()
    await asyncio.sleep(0.05)
    ws2 = await raw_connect(server)
    resp = await auth(ws2, "alice", "pass123")
    assert resp["type"] == "AUTH_OK"
    await ws2.close()


@pytest.mark.asyncio
async def test_login_wrong_password(server):
    ws1 = await raw_connect(server)
    await auth(ws1, "alice", "pass123")
    await ws1.close()
    await asyncio.sleep(0.05)
    ws2 = await raw_connect(server)
    resp = await auth(ws2, "alice", "wrongpass")
    assert resp["type"] == "AUTH_FAIL"
    await ws2.close()


@pytest.mark.asyncio
async def test_duplicate_login(server):
    ws1 = await raw_connect(server)
    await auth(ws1, "alice", "pass123")
    ws2 = await raw_connect(server)
    resp = await auth(ws2, "alice", "pass123")
    assert resp["type"] == "AUTH_FAIL"
    await ws1.close()
    await ws2.close()


@pytest.mark.asyncio
async def test_reconnect_after_disconnect(server):
    ws1 = await raw_connect(server)
    await auth(ws1, "alice", "pass123")
    await ws1.close()
    await asyncio.sleep(0.1)
    ws2 = await raw_connect(server)
    resp = await auth(ws2, "alice", "pass123")
    assert resp["type"] == "AUTH_OK"
    await ws2.close()
```

- [ ] **Step 2: Run tests**

```bash
cd /home/deeptuuk/OnlyCC/Agent_world && pytest tests/test_auth.py -v
```

Expected: All 5 tests PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_auth.py
git commit -m "test: add auth tests - all passing"
```

---

## Chunk 4: Room Tests

### Task 6: Room Operation Tests

**Files:**
- Create: `tests/test_room.py`

- [ ] **Step 1: Write tests/test_room.py**

```python
import json
import pytest
import websockets
from tests.conftest import send, recv_type


@pytest.mark.asyncio
async def test_set_description(client):
    ws = await client("alice", "pass")
    resp = await send(ws, {"type": "SET_DESC", "description": "星空咖啡馆"})
    assert resp["type"] == "DESC_UPDATED"
    resp = await send(ws, {"type": "LOOK"})
    assert resp["type"] == "LOOK_RESULT"
    assert resp["room"]["description"] == "星空咖啡馆"


@pytest.mark.asyncio
async def test_place_item(client):
    ws = await client("alice", "pass")
    resp = await send(ws, {
        "type": "PLACE_ITEM", "icon": "☕", "name": "咖啡机", "description": "自动续杯"
    })
    assert resp["type"] == "ITEM_PLACED"
    assert resp["item"]["name"] == "咖啡机"
    resp = await send(ws, {"type": "LOOK"})
    names = [i["name"] for i in resp["room"]["items"]]
    assert "咖啡机" in names


@pytest.mark.asyncio
async def test_place_duplicate_name(client):
    ws = await client("alice", "pass")
    await send(ws, {"type": "PLACE_ITEM", "icon": "☕", "name": "咖啡机", "description": ""})
    resp = await send(ws, {"type": "PLACE_ITEM", "icon": "🍵", "name": "咖啡机", "description": ""})
    assert resp["type"] == "ERROR"


@pytest.mark.asyncio
async def test_remove_item(client):
    ws = await client("alice", "pass")
    await send(ws, {"type": "PLACE_ITEM", "icon": "☕", "name": "咖啡机", "description": ""})
    resp = await send(ws, {"type": "REMOVE_ITEM", "name": "咖啡机"})
    assert resp["type"] == "ITEM_REMOVED"
    resp = await send(ws, {"type": "LOOK"})
    names = [i["name"] for i in resp["room"]["items"]]
    assert "咖啡机" not in names


@pytest.mark.asyncio
async def test_remove_nonexistent(client):
    ws = await client("alice", "pass")
    resp = await send(ws, {"type": "REMOVE_ITEM", "name": "不存在的物品"})
    assert resp["type"] == "ERROR"


@pytest.mark.asyncio
async def test_look_room(client):
    ws = await client("alice", "pass")
    await send(ws, {"type": "SET_DESC", "description": "我的房间"})
    await send(ws, {"type": "PLACE_ITEM", "icon": "📚", "name": "书架", "description": "满是书"})
    resp = await send(ws, {"type": "LOOK"})
    assert resp["type"] == "LOOK_RESULT"
    assert "room" in resp
    assert resp["room"]["description"] == "我的房间"
    assert any(i["name"] == "书架" for i in resp["room"]["items"])
    assert "owner" in resp["room"]


@pytest.mark.asyncio
async def test_look_specific_item(client):
    ws = await client("alice", "pass")
    await send(ws, {"type": "PLACE_ITEM", "icon": "☕", "name": "吧台", "description": "三杯拿铁"})
    resp = await send(ws, {"type": "LOOK", "item_name": "吧台"})
    assert resp["type"] == "LOOK_RESULT"
    assert resp["item"]["name"] == "吧台"
    assert resp["item"]["description"] == "三杯拿铁"


@pytest.mark.asyncio
async def test_look_nonexistent_item(client):
    ws = await client("alice", "pass")
    resp = await send(ws, {"type": "LOOK", "item_name": "不存在"})
    assert resp["type"] == "ERROR"


@pytest.mark.asyncio
async def test_cannot_modify_others_room(server, client):
    alice = await client("alice", "apass")
    bob = await client("bob", "bpass")

    # bob knocks alice, alice accepts, bob enters
    await send(bob, {"type": "KNOCK", "target": "alice"})
    knock_msg = await recv_type(alice, "KNOCK_RECEIVED")
    await send(alice, {"type": "KNOCK_REPLY", "to": "bob", "accept": True})
    await recv_type(bob, "KNOCK_ACCEPTED")
    await send(bob, {"type": "ENTER", "target": "alice"})
    resp = await recv_type(bob, "ENTER_OK")
    assert resp["type"] == "ENTER_OK"

    # bob tries to place/remove/set_desc in alice's room
    resp = await send(bob, {"type": "PLACE_ITEM", "icon": "🎸", "name": "吉他", "description": ""})
    assert resp["type"] == "ERROR"

    resp = await send(bob, {"type": "REMOVE_ITEM", "name": "something"})
    assert resp["type"] == "ERROR"

    resp = await send(bob, {"type": "SET_DESC", "description": "hacked"})
    assert resp["type"] == "ERROR"
```

- [ ] **Step 2: Run tests**

```bash
pytest tests/test_room.py -v
```

Expected: All 9 tests PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_room.py
git commit -m "test: add room operation tests - all passing"
```

---

## Chunk 5: Social + Chat + E2E Tests

### Task 7: Social Tests

**Files:**
- Create: `tests/test_social.py`

- [ ] **Step 1: Write tests/test_social.py**

```python
import asyncio
import pytest
from tests.conftest import send, recv_type


@pytest.mark.asyncio
async def test_knock_and_accept(client):
    alice = await client("alice", "apass")
    bob = await client("bob", "bpass")

    await send(bob, {"type": "KNOCK", "target": "alice"})
    knock = await recv_type(alice, "KNOCK_RECEIVED")
    assert knock["from"] == "bob"

    await send(alice, {"type": "KNOCK_REPLY", "to": "bob", "accept": True})
    accepted = await recv_type(bob, "KNOCK_ACCEPTED")
    assert accepted["from"] == "alice"


@pytest.mark.asyncio
async def test_knock_and_reject(client):
    alice = await client("alice", "apass")
    bob = await client("bob", "bpass")

    await send(bob, {"type": "KNOCK", "target": "alice"})
    await recv_type(alice, "KNOCK_RECEIVED")

    await send(alice, {"type": "KNOCK_REPLY", "to": "bob", "accept": False})
    rejected = await recv_type(bob, "KNOCK_REJECTED")
    assert rejected["from"] == "alice"


@pytest.mark.asyncio
async def test_knock_offline_target(client):
    bob = await client("bob", "bpass")
    resp = await send(bob, {"type": "KNOCK", "target": "nobody"})
    assert resp["type"] == "ERROR"


@pytest.mark.asyncio
async def test_knock_target_not_home(client):
    alice = await client("alice", "apass")
    bob = await client("bob", "bpass")
    carol = await client("carol", "cpass")

    # bob enters carol's room first
    await send(bob, {"type": "KNOCK", "target": "carol"})
    await recv_type(carol, "KNOCK_RECEIVED")
    await send(carol, {"type": "KNOCK_REPLY", "to": "bob", "accept": True})
    await recv_type(bob, "KNOCK_ACCEPTED")
    await send(bob, {"type": "ENTER", "target": "carol"})
    await recv_type(bob, "ENTER_OK")

    # alice tries to knock bob (who is not home)
    resp = await send(alice, {"type": "KNOCK", "target": "bob"})
    assert resp["type"] == "ERROR"


@pytest.mark.asyncio
async def test_enter_without_acceptance(client):
    alice = await client("alice", "apass")
    bob = await client("bob", "bpass")
    resp = await send(bob, {"type": "ENTER", "target": "alice"})
    assert resp["type"] == "ERROR"


@pytest.mark.asyncio
async def test_enter_accepted_room(client):
    alice = await client("alice", "apass")
    bob = await client("bob", "bpass")

    await send(bob, {"type": "KNOCK", "target": "alice"})
    await recv_type(alice, "KNOCK_RECEIVED")
    await send(alice, {"type": "KNOCK_REPLY", "to": "bob", "accept": True})
    await recv_type(bob, "KNOCK_ACCEPTED")

    resp = await send(bob, {"type": "ENTER", "target": "alice"})
    assert resp["type"] == "ENTER_OK"
    assert resp["room"]["owner"] == "alice"


@pytest.mark.asyncio
async def test_visitor_joined_broadcast(client):
    alice = await client("alice", "apass")
    bob = await client("bob", "bpass")

    await send(bob, {"type": "KNOCK", "target": "alice"})
    await recv_type(alice, "KNOCK_RECEIVED")
    await send(alice, {"type": "KNOCK_REPLY", "to": "bob", "accept": True})
    await recv_type(bob, "KNOCK_ACCEPTED")
    await send(bob, {"type": "ENTER", "target": "alice"})

    joined = await recv_type(alice, "VISITOR_JOINED")
    assert joined["agent"] == "bob"


@pytest.mark.asyncio
async def test_visitor_left_broadcast(client):
    alice = await client("alice", "apass")
    bob = await client("bob", "bpass")

    await send(bob, {"type": "KNOCK", "target": "alice"})
    await recv_type(alice, "KNOCK_RECEIVED")
    await send(alice, {"type": "KNOCK_REPLY", "to": "bob", "accept": True})
    await recv_type(bob, "KNOCK_ACCEPTED")
    await send(bob, {"type": "ENTER", "target": "alice"})
    await recv_type(alice, "VISITOR_JOINED")

    await send(bob, {"type": "HOME"})
    left = await recv_type(alice, "VISITOR_LEFT")
    assert left["agent"] == "bob"


@pytest.mark.asyncio
async def test_home_returns_own_room(client):
    alice = await client("alice", "apass")
    bob = await client("bob", "bpass")

    await send(bob, {"type": "KNOCK", "target": "alice"})
    await recv_type(alice, "KNOCK_RECEIVED")
    await send(alice, {"type": "KNOCK_REPLY", "to": "bob", "accept": True})
    await recv_type(bob, "KNOCK_ACCEPTED")
    await send(bob, {"type": "ENTER", "target": "alice"})
    await recv_type(bob, "ENTER_OK")
    await recv_type(alice, "VISITOR_JOINED")

    resp = await send(bob, {"type": "HOME"})
    assert resp["type"] == "HOME_OK"
    assert resp["room"]["owner"] == "bob"


@pytest.mark.asyncio
async def test_who_lists_visitors(client):
    alice = await client("alice", "apass")
    bob = await client("bob", "bpass")

    await send(bob, {"type": "KNOCK", "target": "alice"})
    await recv_type(alice, "KNOCK_RECEIVED")
    await send(alice, {"type": "KNOCK_REPLY", "to": "bob", "accept": True})
    await recv_type(bob, "KNOCK_ACCEPTED")
    await send(bob, {"type": "ENTER", "target": "alice"})
    await recv_type(bob, "ENTER_OK")
    await recv_type(alice, "VISITOR_JOINED")

    resp = await send(alice, {"type": "WHO"})
    assert resp["type"] == "WHO_RESULT"
    assert "bob" in resp["visitors"]


@pytest.mark.asyncio
async def test_list_online_agents(client):
    alice = await client("alice", "apass")
    bob = await client("bob", "bpass")
    resp = await send(alice, {"type": "LIST"})
    assert resp["type"] == "LIST_RESULT"
    assert "alice" in resp["agents"]
    assert "bob" in resp["agents"]
```

- [ ] **Step 2: Run tests**

```bash
pytest tests/test_social.py -v
```

Expected: All 11 tests PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_social.py
git commit -m "test: add social flow tests - all passing"
```

---

### Task 8: Chat Tests

**Files:**
- Create: `tests/test_chat.py`

- [ ] **Step 1: Write tests/test_chat.py**

```python
import asyncio
import pytest
from tests.conftest import send, recv_type


async def enter_room(guest, host_ws, host_name, guest_name):
    """Helper: guest knocks, host accepts, guest enters."""
    await send(guest, {"type": "KNOCK", "target": host_name})
    await recv_type(host_ws, "KNOCK_RECEIVED")
    await send(host_ws, {"type": "KNOCK_REPLY", "to": guest_name, "accept": True})
    await recv_type(guest, "KNOCK_ACCEPTED")
    await send(guest, {"type": "ENTER", "target": host_name})
    await recv_type(guest, "ENTER_OK")
    await recv_type(host_ws, "VISITOR_JOINED")


@pytest.mark.asyncio
async def test_say_broadcast(client):
    alice = await client("alice", "apass")
    bob = await client("bob", "bpass")
    await enter_room(bob, alice, "alice", "bob")

    await send(bob, {"type": "SAY", "text": "你好"})

    # Both should receive SAID
    alice_msg = await recv_type(alice, "SAID")
    assert alice_msg["from"] == "bob"
    assert alice_msg["text"] == "你好"

    bob_msg = await recv_type(bob, "SAID")
    assert bob_msg["from"] == "bob"


@pytest.mark.asyncio
async def test_say_not_to_other_rooms(client):
    alice = await client("alice", "apass")
    bob = await client("bob", "bpass")
    carol = await client("carol", "cpass")

    # bob enters alice's room, carol stays in own room
    await enter_room(bob, alice, "alice", "bob")

    # bob says something
    await send(bob, {"type": "SAY", "text": "秘密"})
    # alice gets it
    await recv_type(alice, "SAID")
    await recv_type(bob, "SAID")

    # carol should NOT get it
    with pytest.raises((asyncio.TimeoutError, TimeoutError)):
        await recv_type(carol, "SAID", timeout=0.3)


@pytest.mark.asyncio
async def test_whisper_delivery(client):
    alice = await client("alice", "apass")
    bob = await client("bob", "bpass")

    resp = await send(alice, {"type": "WHISPER", "target": "bob", "text": "悄悄话"})
    # No direct response for whisper (not an error)
    # bob should receive WHISPERED
    msg = await recv_type(bob, "WHISPERED")
    assert msg["from"] == "alice"
    assert msg["text"] == "悄悄话"


@pytest.mark.asyncio
async def test_whisper_not_to_others(client):
    alice = await client("alice", "apass")
    bob = await client("bob", "bpass")
    carol = await client("carol", "cpass")

    await send(alice, {"type": "WHISPER", "target": "bob", "text": "只给bob"})
    await recv_type(bob, "WHISPERED")

    with pytest.raises((asyncio.TimeoutError, TimeoutError)):
        await recv_type(carol, "WHISPERED", timeout=0.3)


@pytest.mark.asyncio
async def test_whisper_offline_target(client):
    alice = await client("alice", "apass")
    resp = await send(alice, {"type": "WHISPER", "target": "nobody", "text": "hi"})
    assert resp["type"] == "ERROR"
```

- [ ] **Step 2: Run tests**

```bash
pytest tests/test_chat.py -v
```

Expected: All 5 tests PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_chat.py
git commit -m "test: add chat tests - all passing"
```

---

### Task 9: End-to-End Tests

**Files:**
- Create: `tests/test_e2e.py`

- [ ] **Step 1: Write tests/test_e2e.py**

```python
import asyncio
import pytest
from tests.conftest import send, recv_type


@pytest.mark.asyncio
async def test_full_visit_scenario(client):
    alice = await client("alice", "apass")
    bob = await client("bob", "bpass")

    # 1. alice sets up room
    await send(alice, {"type": "SET_DESC", "description": "爱丽丝的茶室"})
    await send(alice, {"type": "PLACE_ITEM", "icon": "🍵", "name": "茶具", "description": "精美茶具"})
    await send(alice, {"type": "PLACE_ITEM", "icon": "🌸", "name": "樱花", "description": "盛开的樱花"})

    # 2. bob knocks alice
    await send(bob, {"type": "KNOCK", "target": "alice"})

    # 3. alice receives knock
    knock = await recv_type(alice, "KNOCK_RECEIVED")
    assert knock["from"] == "bob"

    # 4. alice accepts
    await send(alice, {"type": "KNOCK_REPLY", "to": "bob", "accept": True})

    # 5. bob receives acceptance
    accepted = await recv_type(bob, "KNOCK_ACCEPTED")
    assert accepted["from"] == "alice"

    # 6. bob enters alice's room
    await send(bob, {"type": "ENTER", "target": "alice"})

    # 7. bob gets ENTER_OK with alice's room state
    enter_ok = await recv_type(bob, "ENTER_OK")
    assert enter_ok["room"]["owner"] == "alice"
    assert enter_ok["room"]["description"] == "爱丽丝的茶室"
    assert len(enter_ok["room"]["items"]) == 2

    # 8. alice gets VISITOR_JOINED
    joined = await recv_type(alice, "VISITOR_JOINED")
    assert joined["agent"] == "bob"

    # 9. bob says hello
    await send(bob, {"type": "SAY", "text": "你好"})

    # 10. alice receives SAID
    said = await recv_type(alice, "SAID")
    assert said["from"] == "bob"
    assert said["text"] == "你好"
    await recv_type(bob, "SAID")  # bob also receives

    # 11. alice whispers to bob
    await send(alice, {"type": "WHISPER", "target": "bob", "text": "欢迎光临"})

    # 12. bob receives WHISPERED
    whispered = await recv_type(bob, "WHISPERED")
    assert whispered["from"] == "alice"
    assert whispered["text"] == "欢迎光临"

    # 13. bob goes home
    await send(bob, {"type": "HOME"})

    # 14. alice receives VISITOR_LEFT
    left = await recv_type(alice, "VISITOR_LEFT")
    assert left["agent"] == "bob"

    # 15. bob receives HOME_OK with own room
    home_ok = await recv_type(bob, "HOME_OK")
    assert home_ok["room"]["owner"] == "bob"


@pytest.mark.asyncio
async def test_three_players_in_room(client):
    alice = await client("alice", "apass")
    bob = await client("bob", "bpass")
    carol = await client("carol", "cpass")

    async def enter(guest, guest_ws, host_name):
        await send(guest_ws, {"type": "KNOCK", "target": host_name})
        await recv_type(alice, "KNOCK_RECEIVED")
        await send(alice, {"type": "KNOCK_REPLY", "to": guest, "accept": True})
        await recv_type(guest_ws, "KNOCK_ACCEPTED")
        await send(guest_ws, {"type": "ENTER", "target": host_name})
        await recv_type(guest_ws, "ENTER_OK")
        await recv_type(alice, "VISITOR_JOINED")

    await enter("bob", bob, "alice")
    await enter("carol", carol, "alice")

    # alice says something, bob and carol both receive
    await send(alice, {"type": "SAY", "text": "欢迎大家"})
    alice_said = await recv_type(alice, "SAID")
    bob_said = await recv_type(bob, "SAID")
    carol_said = await recv_type(carol, "SAID")
    assert all(m["text"] == "欢迎大家" for m in [alice_said, bob_said, carol_said])


@pytest.mark.asyncio
async def test_disconnect_cleanup(client):
    alice = await client("alice", "apass")
    bob = await client("bob", "bpass")

    await send(bob, {"type": "KNOCK", "target": "alice"})
    await recv_type(alice, "KNOCK_RECEIVED")
    await send(alice, {"type": "KNOCK_REPLY", "to": "bob", "accept": True})
    await recv_type(bob, "KNOCK_ACCEPTED")
    await send(bob, {"type": "ENTER", "target": "alice"})
    await recv_type(bob, "ENTER_OK")
    await recv_type(alice, "VISITOR_JOINED")

    # bob disconnects abruptly
    await bob.close()

    # alice should receive VISITOR_LEFT
    left = await recv_type(alice, "VISITOR_LEFT", timeout=3.0)
    assert left["agent"] == "bob"
```

- [ ] **Step 2: Run all tests**

```bash
pytest tests/ -v
```

Expected: All tests PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_e2e.py
git commit -m "test: add end-to-end scenario tests - all passing"
```

---

## Chunk 6: Gateway + CLI

### Task 10: Gateway Daemon

**Files:**
- Create: `client/gateway.py`

- [ ] **Step 1: Write client/gateway.py**

```python
"""
Gateway daemon: maintains WebSocket connection to server,
exposes IPC via Unix Domain Socket.
"""
import asyncio
import atexit
import json
import logging
import os
import signal
import sys
from pathlib import Path
from types import SimpleNamespace

import websockets

import protocol as P

logger = logging.getLogger(__name__)

SOCK_PATH = Path.home() / ".agent" / "sock"
SERVER_URL_DEFAULT = "ws://127.0.0.1:8765"
IPC_TIMEOUT = 10.0


class GatewayState:
    def __init__(self, agent_id: str, ws):
        self.agent_id = agent_id
        self.ws = ws
        self.message_queue: list[dict] = []
        self.pending_response: asyncio.Queue = asyncio.Queue()
        self.current_room: str | None = None  # None = own room


async def ws_recv_loop(state: GatewayState) -> None:
    try:
        async for raw in state.ws:
            msg = json.loads(raw)
            msg_type = msg.get("type", "")
            if msg_type in P.PUSH_TYPES:
                state.message_queue.append(msg)
                # Update room cache
                if msg_type == P.ENTER_OK:
                    state.current_room = msg.get("room", {}).get("owner")
                elif msg_type == P.HOME_OK:
                    state.current_room = None
            else:
                await state.pending_response.put(msg)
                # Update room cache for response types
                if msg_type == P.ENTER_OK:
                    state.current_room = msg.get("room", {}).get("owner")
                elif msg_type == P.HOME_OK:
                    state.current_room = None
    except Exception as e:
        logger.error("WebSocket recv error: %s", e)


async def handle_ipc_connection(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    state: GatewayState,
) -> None:
    try:
        raw = await asyncio.wait_for(reader.readline(), timeout=5.0)
        req = json.loads(raw.decode())
    except Exception:
        writer.close()
        return

    cmd = req.get("cmd")
    args = req.get("args", {})
    response = await handle_ipc_cmd(cmd, args, state)

    writer.write((json.dumps(response) + "\n").encode())
    await writer.drain()
    writer.close()
    await writer.wait_closed()


async def handle_ipc_cmd(cmd: str, args: dict, state: GatewayState) -> dict:
    if cmd == "inbox":
        msgs = list(state.message_queue)
        state.message_queue.clear()
        return {"ok": True, "messages": msgs}

    if cmd == "status":
        room = state.current_room or state.agent_id
        return {"ok": True, "output": f"✓ {state.agent_id} @ {room}"}

    if cmd == "stop":
        asyncio.get_event_loop().call_soon(asyncio.get_event_loop().stop)
        return {"ok": True, "output": "✓ gateway 正在停止"}

    # Passthrough commands
    ws_msg = _build_ws_msg(cmd, args)
    if ws_msg is None:
        return {"ok": False, "output": f"✗ 未知命令: {cmd}"}

    try:
        await state.ws.send(json.dumps(ws_msg))
    except Exception as e:
        return {"ok": False, "output": f"✗ 发送失败: {e}"}

    # Commands that don't wait for a response
    if cmd in ("say", "whisper", "knock_reply"):
        return {"ok": True, "output": "✓ 已发送"}

    if cmd == "knock":
        return {"ok": True, "output": f"⏳ 已向 {args.get('target')} 发送拜访请求"}

    try:
        resp = await asyncio.wait_for(state.pending_response.get(), timeout=IPC_TIMEOUT)
    except asyncio.TimeoutError:
        return {"ok": False, "output": "✗ 服务器响应超时"}

    return _format_response(cmd, resp, state)


def _build_ws_msg(cmd: str, args: dict) -> dict | None:
    mapping = {
        "desc": lambda a: {"type": P.SET_DESC, "description": a.get("description", "")},
        "place": lambda a: {"type": P.PLACE_ITEM, **a},
        "remove": lambda a: {"type": P.REMOVE_ITEM, "name": a.get("name", "")},
        "look": lambda a: {"type": P.LOOK, **({} if not a.get("item_name") else {"item_name": a["item_name"]})},
        "who": lambda a: {"type": P.WHO},
        "list": lambda a: {"type": P.LIST},
        "knock": lambda a: {"type": P.KNOCK, "target": a.get("target", "")},
        "accept": lambda a: {"type": P.KNOCK_REPLY, "to": a.get("to", ""), "accept": True},
        "reject": lambda a: {"type": P.KNOCK_REPLY, "to": a.get("to", ""), "accept": False},
        "enter": lambda a: {"type": P.ENTER, "target": a.get("target", "")},
        "say": lambda a: {"type": P.SAY, "text": a.get("text", "")},
        "whisper": lambda a: {"type": P.WHISPER, **a},
        "home": lambda a: {"type": P.HOME},
    }
    factory = mapping.get(cmd)
    return factory(args) if factory else None


def _format_response(cmd: str, resp: dict, state: GatewayState) -> dict:
    msg_type = resp.get("type", "")
    if msg_type == P.ERROR:
        return {"ok": False, "output": f"✗ {resp.get('reason', '未知错误')}"}

    if msg_type == P.DESC_UPDATED:
        return {"ok": True, "output": "✓ 描述已更新"}

    if msg_type == P.ITEM_PLACED:
        item = resp["item"]
        return {"ok": True, "output": f"✓ 已放置: {item['icon']} {item['name']}"}

    if msg_type == P.ITEM_REMOVED:
        return {"ok": True, "output": f"✓ 已移除: {resp.get('name', '')}"}

    if msg_type == P.LOOK_RESULT:
        if "item" in resp:
            i = resp["item"]
            return {"ok": True, "output": f"{i['icon']} {i['name']}\n  {i['description']}"}
        room = resp["room"]
        items_str = " | ".join(f"{i['icon']} {i['name']}" for i in room.get("items", []))
        visitors_str = ", ".join(room.get("visitors", []))
        lines = [
            f"🏠 {room['owner']} 的房间 — \"{room.get('description', '')}\"",
            f"物品: {items_str or '（空）'}",
            f"在线: {visitors_str or '（无）'}",
        ]
        return {"ok": True, "output": "\n".join(lines)}

    if msg_type == P.WHO_RESULT:
        visitors = ", ".join(resp.get("visitors", []))
        return {"ok": True, "output": f"房间成员: {visitors or '（无）'}"}

    if msg_type == P.LIST_RESULT:
        agents = ", ".join(resp.get("agents", []))
        return {"ok": True, "output": f"在线玩家: {agents}"}

    if msg_type in (P.ENTER_OK, P.HOME_OK):
        room = resp["room"]
        items_str = " | ".join(f"{i['icon']} {i['name']}" for i in room.get("items", []))
        visitors_str = ", ".join(room.get("visitors", []))
        lines = [
            f"🏠 {room['owner']} 的房间 — \"{room.get('description', '')}\"",
            f"物品: {items_str or '（空）'}",
            f"在线: {visitors_str or '（无）'}",
        ]
        return {"ok": True, "output": "\n".join(lines)}

    return {"ok": True, "output": f"✓ {msg_type}"}


async def connect_and_auth(server_url: str, name: str, password: str) -> GatewayState:
    ws = await websockets.connect(server_url)
    await ws.send(json.dumps({"type": P.AUTH, "name": name, "password": password}))
    resp = json.loads(await ws.recv())
    if resp["type"] != P.AUTH_OK:
        await ws.close()
        raise RuntimeError(f"AUTH failed: {resp.get('reason', '')}")
    return GatewayState(agent_id=name, ws=ws)


def cleanup_sock():
    try:
        SOCK_PATH.unlink(missing_ok=True)
    except Exception:
        pass


async def run_gateway(server_url: str, name: str, password: str) -> None:
    sock_dir = SOCK_PATH.parent
    sock_dir.mkdir(parents=True, exist_ok=True)

    # Check for existing gateway
    if SOCK_PATH.exists():
        try:
            _, writer = await asyncio.wait_for(
                asyncio.open_unix_connection(str(SOCK_PATH)), timeout=1.0
            )
            writer.close()
            print("✗ gateway 已在运行")
            return
        except Exception:
            SOCK_PATH.unlink(missing_ok=True)

    state = await connect_and_auth(server_url, name, password)
    print(f"✓ 已连接为 {name}")

    atexit.register(cleanup_sock)

    for sig in (signal.SIGINT, signal.SIGTERM):
        asyncio.get_event_loop().add_signal_handler(sig, cleanup_sock)

    async def ipc_handler(reader, writer):
        await handle_ipc_connection(reader, writer, state)

    ipc_server = await asyncio.start_unix_server(ipc_handler, path=str(SOCK_PATH))

    recv_task = asyncio.create_task(ws_recv_loop(state))

    try:
        async with ipc_server:
            await ipc_server.serve_forever()
    except Exception:
        pass
    finally:
        recv_task.cancel()
        await state.ws.close()
        cleanup_sock()


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Agent World Gateway")
    parser.add_argument("name", help="Agent name")
    parser.add_argument("password", help="Agent password")
    parser.add_argument("--server", default=SERVER_URL_DEFAULT, help="Server URL")
    args = parser.parse_args()
    asyncio.run(run_gateway(args.server, args.name, args.password))


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Commit**

```bash
git add client/gateway.py
git commit -m "feat: add gateway daemon with WebSocket + IPC"
```

---

### Task 11: CLI

**Files:**
- Create: `client/cli.py`

- [ ] **Step 1: Write client/cli.py**

```python
"""CLI commands for Agent World."""
import asyncio
import json
import sys
from pathlib import Path

import click

SOCK_PATH = Path.home() / ".agent" / "sock"


async def _send_ipc(cmd: str, args: dict) -> dict:
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_unix_connection(str(SOCK_PATH)), timeout=3.0
        )
    except Exception:
        click.echo("✗ gateway 未运行")
        sys.exit(1)

    req = json.dumps({"cmd": cmd, "args": args}) + "\n"
    writer.write(req.encode())
    await writer.drain()

    raw = await asyncio.wait_for(reader.readline(), timeout=10.0)
    writer.close()
    await writer.wait_closed()
    return json.loads(raw.decode())


def send_to_gateway(cmd: str, args: dict = None) -> dict:
    return asyncio.run(_send_ipc(cmd, args or {}))


@click.group()
def cli():
    """Agent World CLI."""


@cli.command()
@click.argument("text", nargs=-1, required=True)
def say(text):
    """公开发言。"""
    res = send_to_gateway("say", {"text": " ".join(text)})
    click.echo(res["output"])


@cli.command()
@click.argument("parts", nargs=-1, required=True)
def whisper(parts):
    """私聊。格式: whisper <target> -- <message>"""
    raw = " ".join(parts)
    if " -- " in raw:
        target, text = raw.split(" -- ", 1)
        target = target.strip()
    else:
        click.echo("✗ 格式: agent whisper <target> -- <message>")
        sys.exit(1)
    res = send_to_gateway("whisper", {"target": target, "text": text})
    click.echo(res["output"])


@cli.command()
@click.argument("icon")
@click.argument("parts", nargs=-1, required=True)
def place(icon, parts):
    """放置物品。格式: place <icon> <name> [-- <description>]"""
    raw = " ".join(parts)
    if " -- " in raw:
        name, desc = raw.split(" -- ", 1)
        name = name.strip()
    else:
        name, desc = raw.strip(), ""
    res = send_to_gateway("place", {"icon": icon, "name": name, "description": desc})
    click.echo(res["output"])


@cli.command()
@click.argument("name")
def remove(name):
    """移除物品。"""
    res = send_to_gateway("remove", {"name": name})
    click.echo(res["output"])


@cli.command()
@click.argument("description", nargs=-1, required=True)
def desc(description):
    """设置房间描述。"""
    res = send_to_gateway("desc", {"description": " ".join(description)})
    click.echo(res["output"])


@cli.command()
@click.argument("item_name", required=False)
def look(item_name):
    """查看当前房间或物品。"""
    args = {}
    if item_name:
        args["item_name"] = item_name
    res = send_to_gateway("look", args)
    click.echo(res["output"])


@cli.command()
def who():
    """查看当前房间成员。"""
    res = send_to_gateway("who")
    click.echo(res["output"])


@cli.command(name="list")
def list_cmd():
    """查看所有在线玩家。"""
    res = send_to_gateway("list")
    click.echo(res["output"])


@cli.command()
@click.argument("target")
def knock(target):
    """敲门请求拜访。"""
    res = send_to_gateway("knock", {"target": target})
    click.echo(res["output"])


@cli.command()
@click.argument("requester")
def accept(requester):
    """接受来访请求。"""
    res = send_to_gateway("accept", {"to": requester})
    click.echo(res["output"])


@cli.command()
@click.argument("requester")
def reject(requester):
    """拒绝来访请求。"""
    res = send_to_gateway("reject", {"to": requester})
    click.echo(res["output"])


@cli.command()
@click.argument("target")
def enter(target):
    """进入已接受的房间。"""
    res = send_to_gateway("enter", {"target": target})
    click.echo(res["output"])


@cli.command()
def home():
    """回到自己的房间。"""
    res = send_to_gateway("home")
    click.echo(res["output"])


@cli.command()
def inbox():
    """查看未读消息。"""
    res = send_to_gateway("inbox")
    msgs = res.get("messages", [])
    if not msgs:
        click.echo("📬 暂无新消息")
        return
    click.echo(f"📬 {len(msgs)} 条新消息:")
    for m in msgs:
        t = m.get("type", "")
        if t == "SAID":
            click.echo(f"  [{m['from']}] {m['text']}")
        elif t == "WHISPERED":
            click.echo(f"  [私聊 ← {m['from']}] {m['text']}")
        elif t == "KNOCK_RECEIVED":
            click.echo(f"  🔔 {m['from']} 请求来访")
        elif t == "KNOCK_ACCEPTED":
            click.echo(f"  ✓ {m['from']} 接受了你的来访")
        elif t == "KNOCK_REJECTED":
            click.echo(f"  ✗ {m['from']} 拒绝了你的来访")
        elif t == "VISITOR_JOINED":
            click.echo(f"  → {m['agent']} 进入了房间")
        elif t == "VISITOR_LEFT":
            click.echo(f"  ← {m['agent']} 离开了房间")
        else:
            click.echo(f"  {t}: {m}")


@cli.command()
def status():
    """查看当前状态。"""
    res = send_to_gateway("status")
    click.echo(res["output"])


@cli.command()
def stop():
    """停止 gateway。"""
    res = send_to_gateway("stop")
    click.echo(res["output"])


if __name__ == "__main__":
    cli()
```

- [ ] **Step 2: Commit**

```bash
git add client/cli.py
git commit -m "feat: add CLI with click commands"
```

---

## Chunk 7: Final Verification

### Task 12: Run All Tests

- [ ] **Step 1: Run complete test suite**

```bash
cd /home/deeptuuk/OnlyCC/Agent_world && pytest tests/ -v
```

Expected: All tests PASS (green).

- [ ] **Step 2: Verify server starts**

```bash
# Terminal 1: start server
python -m server.main &
SERVER_PID=$!
sleep 1

# Check it's running
echo "Server started with PID $SERVER_PID"
kill $SERVER_PID
```

- [ ] **Step 3: Final commit**

```bash
git add -A
git commit -m "feat: complete Agent World MVP - server + tests + gateway + CLI"
```

---

**Plan complete and saved to `docs/superpowers/plans/2026-03-12-agent-world.md`.**

Ready to execute?
