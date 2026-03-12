# CLAUDE.md — Agent World

## 项目概述

一个面向 Agent 的多人实时交互系统。每个参与者（人类或 AI Agent）拥有自己的房间，可以布置物品、接待访客、聊天互动。

架构为三层模型：
- **中心服务器**：WebSocket 长连接，消息路由，SQLite 持久化
- **本地 gateway**：常驻进程，维持与服务器的 WebSocket 连接，缓存推送消息，通过 Unix Domain Socket 暴露 IPC 接口
- **CLI 命令**：单次执行，通过 IPC 与 gateway 通信，拿到结果后退出

类比：Docker daemon + docker CLI 的关系。

## 目录结构

```
agent-world/
├── CLAUDE.md
├── README.md
├── requirements.txt
├── protocol.py                # 共享消息类型常量
├── server/
│   ├── __init__.py
│   ├── main.py                # WebSocket 服务入口
│   ├── db.py                  # SQLite 初始化 + 异步查询封装
│   └── handlers.py            # 消息处理函数（每个 type 一个函数）
├── client/
│   ├── __init__.py
│   ├── gateway.py             # 常驻进程：WebSocket 上行 + UDS 下行
│   └── cli.py                 # click 命令定义 + IPC 调用
└── tests/
    ├── __init__.py
    ├── conftest.py            # 共享 fixture（服务器、gateway、客户端）
    ├── test_auth.py
    ├── test_room.py
    ├── test_social.py
    ├── test_chat.py
    └── test_e2e.py
```

## 依赖

```
# server
websockets>=12.0
aiosqlite>=0.19.0

# client
websockets>=12.0
click>=8.0

# dev/test
pytest>=8.0
pytest-asyncio>=0.23.0
```

不使用 aioconsole。CLI 是单次执行模式，不需要异步终端输入。
不使用 FastAPI / HTTP。服务器仅提供 WebSocket 接口。

## 协议规范

### 传输

- 服务器监听 WebSocket，默认端口 `8765`
- gateway 监听 Unix Domain Socket，路径 `~/.agent/sock`
- 所有消息均为 UTF-8 编码的 JSON 字符串
- 每条消息必须包含 `"type"` 字段

### 消息类型总表

方向标记：C=CLI, G=gateway, S=服务器

```
类型                方向      触发命令          说明
─────────────────────────────────────────────────────────────
AUTH                G→S      gateway 启动时     登录/注册
AUTH_OK             S→G                        登录成功，返回房间状态
AUTH_FAIL           S→G                        登录失败

SET_DESC            G→S      agent desc        设定房间描述
DESC_UPDATED        S→G                        确认更新

PLACE_ITEM          G→S      agent place       放置物品
ITEM_PLACED         S→G                        确认放置，返回 item 数据
REMOVE_ITEM         G→S      agent remove      移除物品
ITEM_REMOVED        S→G                        确认移除

LOOK                G→S      agent look        请求房间/物品信息
LOOK_RESULT         S→G                        返回房间或物品详情

WHO                 G→S      agent who         查询房间内人员
WHO_RESULT          S→G                        返回人员列表

LIST                G→S      agent list        查询在线玩家
LIST_RESULT         S→G                        返回在线列表

KNOCK               G→S      agent knock       请求拜访
KNOCK_RECEIVED      S→G                        通知房主有人敲门（推送）
KNOCK_REPLY         G→S      agent accept/reject  房主回应
KNOCK_ACCEPTED      S→G                        通知请求者被接受（推送）
KNOCK_REJECTED      S→G                        通知请求者被拒绝（推送）

ENTER               G→S      agent enter       进入已接受的房间
ENTER_OK            S→G                        确认进入，返回房间状态
VISITOR_JOINED      S→G                        广播：有人进入房间（推送）
VISITOR_LEFT        S→G                        广播：有人离开房间（推送）

SAY                 G→S      agent say         公开说话
SAID                S→G                        广播给房间内所有人（推送）

WHISPER             G→S      agent whisper     私聊
WHISPERED           S→G                        点对点送达（推送）

HOME                G→S      agent home        回到自己房间
HOME_OK             S→G                        确认回家，返回自己房间状态

ERROR               S→G                        错误响应，附 reason 字段
```

### 消息结构示例

```json
// AUTH
{"type": "AUTH", "name": "nick", "password": "123"}
{"type": "AUTH_OK", "agent_id": "nick", "room": {"description": "", "items": [], "visitors": []}}

// PLACE_ITEM
{"type": "PLACE_ITEM", "icon": "☕", "name": "咖啡机", "description": "自动续杯的神器"}
{"type": "ITEM_PLACED", "item": {"id": 1, "icon": "☕", "name": "咖啡机", "description": "自动续杯的神器"}}

// KNOCK 流程
{"type": "KNOCK", "target": "luna"}
{"type": "KNOCK_RECEIVED", "from": "nick"}           // 推送给 luna
{"type": "KNOCK_REPLY", "to": "nick", "accept": true} // luna 回应
{"type": "KNOCK_ACCEPTED", "from": "luna"}             // 推送给 nick

// SAY
{"type": "SAY", "text": "来杯拿铁"}
{"type": "SAID", "from": "nick", "text": "来杯拿铁", "room": "luna"}

// WHISPER
{"type": "WHISPER", "target": "luna", "text": "私聊内容"}
{"type": "WHISPERED", "from": "nick", "text": "私聊内容"}

// LOOK
{"type": "LOOK"}
{"type": "LOOK_RESULT", "room": {"owner": "luna", "description": "星空咖啡馆", "items": [...], "visitors": [...]}}
{"type": "LOOK", "item_name": "吧台"}
{"type": "LOOK_RESULT", "item": {"id": 1, "icon": "☕", "name": "吧台", "description": "摆着三杯拿铁"}}

// ERROR
{"type": "ERROR", "reason": "目标玩家不在线"}
```

### 请求-响应配对

gateway 向服务器发送命令后，需要等待对应的响应。配对规则：

| 请求            | 成功响应        | 失败响应 |
|----------------|----------------|---------|
| AUTH           | AUTH_OK        | AUTH_FAIL |
| SET_DESC       | DESC_UPDATED   | ERROR |
| PLACE_ITEM     | ITEM_PLACED    | ERROR |
| REMOVE_ITEM    | ITEM_REMOVED   | ERROR |
| LOOK           | LOOK_RESULT    | ERROR |
| WHO            | WHO_RESULT     | ERROR |
| LIST           | LIST_RESULT    | ERROR |
| KNOCK          | KNOCK_ACCEPTED / KNOCK_REJECTED (异步) | ERROR |
| KNOCK_REPLY    | (无直接响应)    | ERROR |
| ENTER          | ENTER_OK       | ERROR |
| SAY            | (无直接响应，广播 SAID 包含自己) | ERROR |
| WHISPER        | (无直接响应)    | ERROR |
| HOME           | HOME_OK        | ERROR |

注意：KNOCK 是异步的。发出 KNOCK 后服务器不会立即返回成功/失败，而是等房主回应后才推送 KNOCK_ACCEPTED 或 KNOCK_REJECTED。gateway 对 CLI 的 knock 命令应立即返回"已发送请求"，不阻塞等待。

对于 SAY，服务器广播 SAID 给房间内所有人包括发言者自身，gateway 收到后存入消息队列。CLI 端 say 命令发出后立即返回"✓ 已发送"。

## 数据库 Schema

SQLite 单文件，路径 `server/world.db`。

```sql
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

-- 同一个房间内物品名不重复
CREATE UNIQUE INDEX IF NOT EXISTS idx_room_items_owner_name
    ON room_items(owner_id, name);
```

运行时状态不入库，全部在 server 内存中维护：

```python
connections: dict[str, WebSocket]       # agent_id -> ws
locations: dict[str, str | None]        # agent_id -> room_owner_id (None = 自己房间)
pending_knocks: dict[str, set[str]]     # room_owner_id -> {requester_ids}
```

### 密码处理

MVP 阶段使用 `hashlib.sha256(password.encode()).hexdigest()` 做最简单的哈希。
不加盐、不用 bcrypt。后续迭代时替换。

## 服务器设计规范

### main.py

- 使用 `websockets.serve` 启动，监听 `0.0.0.0:8765`
- 每个连接进入 `on_connect(ws)` 协程
- 第一条消息必须是 AUTH，否则断开
- AUTH 成功后进入消息循环，调用 `handlers.dispatch()`
- 连接关闭时执行清理：从 connections/locations 移除，广播 VISITOR_LEFT

### handlers.py

- 入口函数 `async def dispatch(ws, msg, agent_id, state)` 根据 `msg["type"]` 分发
- `state` 是一个 dataclass 或 SimpleNamespace，持有 connections/locations/pending_knocks
- 每个 handler 签名统一：`async def handle_xxx(ws, msg, agent_id, state)`
- handler 内部负责参数校验、数据库读写、构造响应、广播
- 所有错误通过发送 `{"type": "ERROR", "reason": "..."}` 返回，不抛异常

### db.py

- `init_db()` 建表
- 每个操作一个函数，签名明确：
  - `get_agent(agent_id) -> dict | None`
  - `create_agent(agent_id, password_hash) -> dict`
  - `update_room_desc(agent_id, desc)`
  - `add_item(owner_id, icon, name, desc) -> dict`
  - `remove_item(owner_id, name) -> bool`
  - `get_room(owner_id) -> dict`  # 返回 {description, items}
  - `get_item(owner_id, item_name) -> dict | None`
- 所有函数使用 `aiosqlite`，async def
- 每个写操作函数内部自行 commit

### 广播辅助

```python
async def broadcast_to_room(state, room_owner_id, msg, exclude=None):
    """向房间内所有人发消息，可排除指定 agent"""
    for aid, loc in state.locations.items():
        actual_room = loc if loc else aid  # None 表示在自己房间
        if actual_room == room_owner_id and aid != exclude:
            if aid in state.connections:
                await state.connections[aid].send(json.dumps(msg))
```

### 位置模型

- `locations[agent_id]` 为 `None` 表示在自己房间
- `locations[agent_id]` 为某个 `owner_id` 表示在别人房间
- 判断"当前所在房间的 owner_id"：`locations.get(agent_id) or agent_id`
- 只有在自己房间时才能执行 desc/place/remove
- 只有在自己房间时才能 accept/reject 来访

## gateway 设计规范

### gateway.py

常驻进程，两个并行协程：

1. `ws_recv_loop`：持续读取服务器 WebSocket 推送
   - 请求-响应消息：放入 `pending_response` (asyncio.Queue)，供 IPC handler 等待
   - 纯推送消息（SAID, WHISPERED, KNOCK_RECEIVED, VISITOR_JOINED, VISITOR_LEFT）：追加到 `message_queue`
   - 房间状态变更（ENTER_OK, HOME_OK）：更新本地 `current_room` 缓存

2. `ipc_serve_loop`：监听 Unix Domain Socket `~/.agent/sock`
   - 每个 CLI 连接：读取一条 JSON 请求，处理，返回一条 JSON 响应，关闭
   - 本地命令（inbox, status）直接从缓存应答
   - 穿透命令：发给服务器，从 `pending_response` 等待结果，超时 10 秒

### IPC 协议 (CLI ↔ gateway)

```json
// 请求
{"cmd": "say", "args": {"text": "你好"}}
{"cmd": "look", "args": {}}
{"cmd": "look", "args": {"item_name": "吧台"}}
{"cmd": "knock", "args": {"target": "luna"}}
{"cmd": "place", "args": {"icon": "☕", "name": "咖啡机", "description": "..."}}
{"cmd": "inbox", "args": {}}
{"cmd": "status", "args": {}}
{"cmd": "stop", "args": {}}

// 响应
{"ok": true, "output": "✓ 已发送。"}
{"ok": true, "output": "🏠 nick 的房间 ..."}
{"ok": true, "messages": [...]}        // inbox 专用
{"ok": false, "output": "✗ 目标玩家不在线"}
```

### gateway 状态

```python
class GatewayState:
    agent_id: str
    ws: WebSocket
    message_queue: list[dict]          # 未读推送消息
    pending_response: asyncio.Queue    # 等待服务器响应
    current_room: str | None           # 当前所在房间 owner_id，None=自己房间
```

### 消息分类逻辑

gateway 收到服务器消息时的分类：

```python
# 推送消息 → 存入 message_queue，不唤醒 pending_response
PUSH_TYPES = {"SAID", "WHISPERED", "KNOCK_RECEIVED",
              "KNOCK_ACCEPTED", "KNOCK_REJECTED",
              "VISITOR_JOINED", "VISITOR_LEFT"}

# 响应消息 → 放入 pending_response 队列
RESPONSE_TYPES = {"AUTH_OK", "AUTH_FAIL", "DESC_UPDATED",
                  "ITEM_PLACED", "ITEM_REMOVED",
                  "LOOK_RESULT", "WHO_RESULT", "LIST_RESULT",
                  "ENTER_OK", "HOME_OK", "ERROR"}
```

### gateway 生命周期

- 启动：连接服务器 → 发 AUTH → 等 AUTH_OK → 开始监听 UDS
- 运行：两个协程并行（ws_recv_loop + ipc_serve_loop）
- 停止：收到 CLI 的 stop 命令 → 关闭 WebSocket → 删除 sock 文件 → 退出
- 异常：服务器断开时，打印错误信息，清理 sock 文件，退出进程

### sock 文件管理

- 启动时检查 `~/.agent/sock` 是否已存在
  - 存在则尝试连接，能连通说明已有 gateway 运行，打印提示并退出
  - 存在但连不通说明是残留文件，删除后继续启动
- 退出时（正常或异常）务必删除 sock 文件，使用 `atexit` 和信号处理确保清理

## CLI 设计规范

### cli.py

使用 `click` 库。入口 group 为 `agent`。

每个命令的职责极简：
1. 解析参数
2. 通过 IPC 发送给 gateway
3. 打印 gateway 返回的 output
4. 退出

### 命令实现模式

```python
def send_to_gateway(cmd: str, args: dict = None) -> dict:
    """同步函数。连接 UDS，发送请求，等待响应，返回结果。"""
    # 内部用 asyncio.run 包装异步 IPC 调用
    # 连接失败时打印 "✗ gateway 未运行" 并 sys.exit(1)
```

所有命令结构相同：

```python
@cli.command()
@click.argument("text", nargs=-1, required=True)
def say(text):
    res = send_to_gateway("say", {"text": " ".join(text)})
    click.echo(res["output"])
```

### 输出格式规范

```
成功操作：  ✓ 具体信息
失败操作：  ✗ 错误原因
房间展示：  🏠 owner 的房间 — "描述"
           物品: ☕ 咖啡机 | 🎵 点唱机
           在线: nick, luna
敲门通知：  🔔 nick 请求来访
消息展示：  [nick] 消息内容
私聊展示：  [私聊 ← nick] 消息内容
系统提示：  ⏳ 等待中...
信箱标题：  📬 N 条新消息:
```

### place 命令解析

`agent place ☕ 咖啡机 -- 自动续杯的神器`

用 `--` 分隔名字和描述。如果没有 `--`，则描述为空。

```python
@cli.command()
@click.argument("icon")
@click.argument("parts", nargs=-1)
def place(icon, parts):
    raw = " ".join(parts)
    if " -- " in raw:
        name, desc = raw.split(" -- ", 1)
    else:
        name, desc = raw, ""
    res = send_to_gateway("place", {"icon": icon, "name": name, "description": desc})
    click.echo(res["output"])
```

### whisper 命令解析

`agent whisper luna -- 私聊内容`

同样用 `--` 分隔目标和内容。

## 测试规范

### 框架与配置

使用 pytest + pytest-asyncio。

```ini
# pyproject.toml 或 pytest.ini
[tool:pytest]
asyncio_mode = auto
```

### conftest.py 核心 fixture

```python
import pytest
import asyncio
import json
import websockets
from server.main import create_server
from server.db import init_db

@pytest.fixture
async def server():
    """启动一个测试服务器，使用内存数据库，测试结束后关闭。"""
    db = await init_db(":memory:")
    state, ws_server = await create_server(db, host="127.0.0.1", port=0)
    port = ws_server.sockets[0].getsockname()[1]
    yield {"port": port, "state": state, "db": db}
    ws_server.close()
    await ws_server.wait_closed()

@pytest.fixture
async def client(server):
    """返回一个工厂函数，用于创建已认证的 WebSocket 客户端。"""
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
        await ws.close()

async def send(ws, msg):
    """辅助函数：发送并接收一条响应。"""
    await ws.send(json.dumps(msg))
    return json.loads(await ws.recv())

async def recv_type(ws, expected_type, timeout=2.0):
    """辅助函数：持续接收直到收到指定类型的消息。"""
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

### 测试分层

**test_auth.py — 认证**

```
test_register_new_agent          首次登录自动注册，返回 AUTH_OK
test_login_existing_agent        已存在用户正确密码登录成功
test_login_wrong_password        密码错误返回 AUTH_FAIL
test_duplicate_login             同名用户已在线时拒绝第二个连接
test_reconnect_after_disconnect  断线后重新登录恢复状态
```

**test_room.py — 房间操作**

```
test_set_description             设定描述后 look 能看到
test_place_item                  放置物品后 look 包含该物品
test_place_duplicate_name        同名物品返回 ERROR
test_remove_item                 移除物品后 look 不包含
test_remove_nonexistent          移除不存在物品返回 ERROR
test_look_room                   返回完整房间信息
test_look_specific_item          返回指定物品详情
test_look_nonexistent_item       查看不存在物品返回 ERROR
test_cannot_modify_others_room   在别人房间执行 place/remove/desc 返回 ERROR
```

**test_social.py — 社交流程**

```
test_knock_and_accept            完整敲门→接受→进入流程
test_knock_and_reject            敲门→拒绝流程
test_knock_offline_target        目标不在线返回 ERROR
test_knock_target_not_home       目标在别人房间时返回 ERROR
test_enter_without_acceptance    未被接受时 enter 返回 ERROR
test_enter_accepted_room         被接受后成功进入
test_visitor_joined_broadcast    进入房间后其他人收到 VISITOR_JOINED
test_visitor_left_broadcast      离开房间后其他人收到 VISITOR_LEFT
test_home_returns_own_room       home 命令返回自己的房间状态
test_who_lists_visitors          who 返回正确的在场人员
test_list_online_agents          list 返回所有在线玩家
```

**test_chat.py — 聊天**

```
test_say_broadcast               say 广播给同房间所有人
test_say_not_to_other_rooms      say 不泄漏到其他房间
test_whisper_delivery            whisper 送达目标
test_whisper_not_to_others       whisper 不送达第三方
test_whisper_offline_target      目标不在线返回 ERROR
```

**test_e2e.py — 端到端场景**

```
test_full_visit_scenario:
    1. alice 注册，布置房间（place 两个物品，设描述）
    2. bob 注册
    3. bob knock alice
    4. alice 收到 KNOCK_RECEIVED
    5. alice accept bob
    6. bob 收到 KNOCK_ACCEPTED
    7. bob enter alice
    8. bob 收到 ENTER_OK（包含 alice 房间完整状态）
    9. alice 收到 VISITOR_JOINED
    10. bob say "你好"
    11. alice 收到 SAID
    12. alice whisper bob "私聊"
    13. bob 收到 WHISPERED
    14. bob home
    15. alice 收到 VISITOR_LEFT
    16. bob 收到 HOME_OK（包含自己房间状态）

test_three_players_in_room:
    三人在同一房间，验证广播正确性

test_disconnect_cleanup:
    玩家在别人房间时断开连接，验证 VISITOR_LEFT 被广播
```

### 测试原则

- 所有测试使用内存数据库 (`:memory:`)，不产生文件
- 每个测试用例独立，不依赖其他测试的执行顺序
- 测试直接对 WebSocket 协议层测试，不测 gateway/CLI（那些是薄封装）
- 涉及多客户端的测试使用 `recv_type` 辅助函数避免消息顺序敏感
- 超时设为 2 秒，避免测试卡死

### 运行测试

```bash
# 全部测试
pytest tests/ -v

# 单个文件
pytest tests/test_auth.py -v

# 单个用例
pytest tests/test_e2e.py::test_full_visit_scenario -v
```

## 开发顺序

### Phase 1 — 服务器核心（可测试）

1. `protocol.py`
2. `server/db.py` + `tests/test_auth.py`（仅数据库层）
3. `server/handlers.py` 实现 AUTH + LOOK
4. `server/main.py` 启动骨架
5. `tests/conftest.py` + `tests/test_auth.py`（WebSocket 层）

验收标准：`pytest tests/test_auth.py` 全绿。

### Phase 2 — 房间操作

6. handlers 实现 SET_DESC + PLACE_ITEM + REMOVE_ITEM + LOOK（完整）
7. `tests/test_room.py`

验收标准：`pytest tests/test_room.py` 全绿。

### Phase 3 — 社交流程

8. handlers 实现 KNOCK + KNOCK_REPLY + ENTER + HOME + WHO + LIST
9. `tests/test_social.py`

验收标准：`pytest tests/test_social.py` 全绿。

### Phase 4 — 聊天

10. handlers 实现 SAY + WHISPER
11. `tests/test_chat.py`

验收标准：`pytest tests/test_chat.py` 全绿。

### Phase 5 — 端到端

12. `tests/test_e2e.py`

验收标准：`pytest tests/` 全绿。

### Phase 6 — gateway

13. `client/gateway.py`

手动测试：启动服务器 → 启动 gateway → 用 wscat 或脚本模拟另一个玩家 → 检查 message_queue。

### Phase 7 — CLI

14. `client/cli.py`

手动测试：两个终端，两个 gateway，完整走一遍拜访流程。

## 编码规范

- Python 3.11+，使用 type hints
- 异步函数统一用 `async def`，不混用线程
- JSON 消息体的 key 一律小写 snake_case
- 错误一律通过 `{"type": "ERROR", "reason": "..."}` 返回，不发送 WebSocket close frame
- 日志使用标准库 `logging`，服务器打印每个连接的 AUTH 和断开事件
- 单个函数不超过 40 行。如果超了，拆分
- 不使用全局变量。运行时状态通过 `state` 对象传递

## 后续迭代方向（MVP 之后）

- AI Agent 接入：gateway 的 IPC 接口对 LLM 脚本同样可用
- Web 渲染层：读取 LOOK_RESULT 的 JSON 渲染为可交互页面
- 好友系统
- 仓库与物品铸造经济
- 皮肤与商城