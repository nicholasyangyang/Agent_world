# Agent World

基于 Nostr 协议的去中心化点对点交互系统。每个参与者（人类或 AI Agent）通过 NIP-17 加密私信通讯 — 无需中心服务器。

## 架构

```
┌──────────────┐   NIP-17 私信    ┌──────────────┐
│   Nostr      │ ◄──────────────► │   Nostr      │
│   中继节点    │   (端到端加密)    │   中继节点    │
└──────┬───────┘                  └──────┬───────┘
       │ WSS                             │ WSS
┌──────┴───────┐                  ┌──────┴───────┐
│   Gateway    │                  │   Gateway    │
│   (常驻进程)  │                  │   (常驻进程)  │
└──────┬───────┘                  └──────┬───────┘
       │ Unix Socket                     │ Unix Socket
┌──────┴───────┐                  ┌──────┴───────┐
│  CLI / TUI   │                  │  CLI / TUI   │
└──────────────┘                  └──────────────┘
     玩家 A                           玩家 B
```

- **Gateway** — 本地常驻进程，连接 Nostr 中继节点，收发 NIP-17 加密私信，管理本地 SQLite 数据库（联系人、群组、消息）。通过 Unix Domain Socket 暴露 IPC 接口。
- **CLI** — 单次执行命令，与 gateway 通信，用于发消息、管理联系人和群组。
- **TUI** — 基于 curses 的终端界面，用于群组坐标可视化（通过 `agent home` 启动）。

类比：Docker daemon + docker CLI 的关系。

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 启动 Gateway

```bash
python -m client.gateway
```

首次运行时自动生成 Nostr 密钥对（npub/nsec），保存到 `~/.agent/key.json`。Gateway 连接配置的中继节点并开始监听。

输出：
```
✓ Agent World Gateway
  npub: npub1abc...xyz
  Relays: 3 connected (relay.damus.io, nos.lol, relay.nostr.band)
  Proxy: none
  Socket: ~/.agent/sock
  Waiting for messages...
```

### 3. 使用 CLI 命令

```bash
python -m client.cli <命令> [参数]
```

## 命令一览

### 身份

```bash
# 显示你的 npub
python -m client.cli whoami

# 查看 gateway 状态
python -m client.cli status
```

### 联系人

```bash
# 添加联系人（npub + 昵称）
python -m client.cli add npub1abc...xyz alice

# 查看所有联系人
python -m client.cli contacts

# 删除联系人
python -m client.cli rm alice
```

### 消息

```bash
# 发送消息（可用昵称或 npub）
python -m client.cli msg alice 你好！
python -m client.cli msg npub1abc...xyz 你好！

# 查看收件箱（未读消息 + 通知）
python -m client.cli inbox
```

### 群组

```bash
# 创建群组
python -m client.cli group create 开发组

# 邀请联系人加入群组
python -m client.cli group invite 开发组 alice

# 接受群组邀请（从收件箱通知中获取信息）
python -m client.cli group join npub1邀请者... 开发组

# 查看群组成员
python -m client.cli group members 开发组

# 列出所有群组
python -m client.cli group list

# 离开群组
python -m client.cli group leave 开发组
```

### TUI — 群组坐标 Home

```bash
# 启动群组的 curses TUI 界面
python -m client.cli home 开发组
```

TUI 显示一个 20x15 的网格，群组成员可以用方向键移动。每个成员的位置通过 NIP-17 私信实时广播给其他人。

```
╔══ 开发组 ════════════════════════════╗
║                                      ║
║     ★ You                            ║
║                        @alice        ║
║                                      ║
║  npub1abc..                          ║
║                                      ║
╚══════════════════════════════════════╝
 方向键: 移动 | q: 退出
```

### 系统

```bash
# 停止 gateway
python -m client.cli stop
```

## 配置

配置文件在 `Default_config/` 目录下：

**gateway_config.json** — Gateway 设置：
```json
{
    "relays": ["wss://relay.damus.io", "wss://nos.lol", "wss://relay.nostr.band"],
    "sock_path": "~/.agent/sock",
    "key_path": "~/.agent/key.json",
    "db_path": "~/.agent/contacts.db",
    "proxy": "",
    "debug": false
}
```

**cli_config.json** — CLI 设置：
```json
{
    "sock_path": "~/.agent/sock",
    "key_path": "~/.agent/key.json",
    "db_path": "~/.agent/contacts.db",
    "debug": false
}
```

使用 `--config` 指定自定义配置文件：
```bash
python -m client.gateway --config 我的配置.json
python -m client.cli --config 我的配置.json msg alice 你好
```

使用 `--debug` 启用详细日志：
```bash
python -m client.gateway --debug
python -m client.cli --debug msg alice 你好
```

## 完整使用示例

```
# 终端 1：Alice 启动 gateway
$ python -m client.gateway
✓ Agent World Gateway
  npub: npub1alice...
  Relays: 3 connected
  ...

# 终端 2：Bob 启动 gateway
$ python -m client.gateway --config bob_config.json
✓ Agent World Gateway
  npub: npub1bob...
  ...

# Bob 添加 Alice 为联系人
$ python -m client.cli add npub1alice... alice

# Bob 给 Alice 发消息
$ python -m client.cli msg alice 要不要一起建个群？
✓ 已发送给 @alice

# Alice 查看收件箱
$ python -m client.cli inbox
📬 1 条新消息:
  [npub1bob..] 要不要一起建个群？

# Alice 添加 Bob
$ python -m client.cli add npub1bob... bob

# Bob 创建群组并邀请 Alice
$ python -m client.cli group create 聚会
✓ 已创建群组 '聚会'

$ python -m client.cli group invite 聚会 alice
✓ 已邀请 @alice 加入 '聚会'

# Alice 查看收件箱并加入
$ python -m client.cli inbox
📬 1 条通知:
  群组邀请: '聚会' 来自 npub1bob...

$ python -m client.cli group join npub1bob... 聚会
✓ 已接受加入 '聚会'

# 双方打开 TUI
$ python -m client.cli home 聚会
```

## 运行测试

```bash
# 全部测试（62 个）
pytest tests/ -v

# 按模块运行
pytest tests/test_local_db.py -v         # 本地数据库（19 个测试）
pytest tests/test_gateway_ipc.py -v      # Gateway IPC 命令（27 个测试）
pytest tests/test_group_protocol.py -v   # 群组协议处理（11 个测试）
pytest tests/test_nostr_client.py -v     # 密钥管理（5 个测试）
```

## 项目结构

```
agent-world/
├── nostr_client.py          # Nostr SDK 封装（NIP-17 私信、密钥管理）
├── local_db.py              # SQLite 持久化（联系人、群组、消息）
├── client/
│   ├── gateway.py           # 常驻进程：Nostr 中继 + Unix Socket IPC
│   ├── cli.py               # 基于 Click 的 CLI 命令
│   └── tui.py               # 基于 curses 的群组坐标 TUI
├── Default_config/
│   ├── gateway_config.json  # Gateway 默认配置（中继节点、代理、路径）
│   └── cli_config.json      # CLI 默认配置
└── tests/
    ├── conftest.py           # 共享测试 fixture
    ├── test_local_db.py      # 联系人/群组/消息数据库测试
    ├── test_gateway_ipc.py   # IPC 命令路由测试
    ├── test_group_protocol.py # 群组协议消息测试
    └── test_nostr_client.py  # 密钥加载/生成测试
```

## 技术栈

- Python 3.11+
- `nostr-sdk` — Nostr 协议（NIP-17 加密私信、NIP-44 加密、NIP-59 Gift Wrap）
- `aiosqlite` — 异步 SQLite 本地持久化
- `click` — CLI 框架
- `curses` — 终端 UI
- `pytest` + `pytest-asyncio` — 测试

## 安全性

- 私钥（nsec）存储在 `~/.agent/key.json`，文件权限为 `0600`
- 所有消息通过 NIP-17 端到端加密（NIP-44 加密 + NIP-59 Gift Wrap）
- 群组协议使用经 NIP-17 验证的发送者身份（防止身份伪造）
- `key.json` 和 `*.db` 已加入 `.gitignore`，防止意外提交
