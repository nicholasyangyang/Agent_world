# Agent World

A decentralized peer-to-peer interaction system built on the Nostr protocol. Each participant (human or AI agent) communicates via NIP-17 encrypted direct messages — no central server required.

## Architecture

```
┌──────────────┐   NIP-17 DMs     ┌──────────────┐
│   Nostr      │ ◄──────────────► │   Nostr      │
│   Relays     │   (encrypted)    │   Relays     │
└──────┬───────┘                  └──────┬───────┘
       │ WSS                             │ WSS
┌──────┴───────┐                  ┌──────┴───────┐
│   Gateway    │                  │   Gateway    │
│   (daemon)   │                  │   (daemon)   │
└──────┬───────┘                  └──────┬───────┘
       │ Unix Socket                     │ Unix Socket
┌──────┴───────┐                  ┌──────┴───────┐
│   CLI / TUI  │                  │   CLI / TUI  │
└──────────────┘                  └──────────────┘
     Player A                         Player B
```

- **Gateway** — Local daemon that connects to Nostr relays, sends/receives NIP-17 encrypted DMs, manages local SQLite database for contacts and groups. Exposes IPC via Unix Domain Socket.
- **CLI** — Single-shot commands that talk to the gateway for messaging, contacts, groups.
- **TUI** — Curses-based terminal UI for group coordinate visualization (launched via `agent home`).

## Quick Start

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Start the gateway

```bash
python -m client.gateway
```

On first run, a new Nostr keypair (npub/nsec) is generated and saved to `~/.agent/key.json`. The gateway connects to configured relays and starts listening.

Output:
```
✓ Agent World Gateway
  npub: npub1abc...xyz
  Relays: 3 connected (relay.damus.io, nos.lol, relay.nostr.band)
  Proxy: none
  Socket: ~/.agent/sock
  Waiting for messages...
```

### 3. Use CLI commands

```bash
python -m client.cli <command> [args]
```

## Commands

### Identity

```bash
# Show your npub
python -m client.cli whoami

# Check gateway status
python -m client.cli status
```

### Contacts

```bash
# Add a contact with a nickname
python -m client.cli add npub1abc...xyz alice

# List all contacts
python -m client.cli contacts

# Remove a contact
python -m client.cli rm alice
```

### Messaging

```bash
# Send a message (by nickname or npub)
python -m client.cli msg alice Hello!
python -m client.cli msg npub1abc...xyz Hello!

# Check inbox (unread messages + notifications)
python -m client.cli inbox
```

### Groups

```bash
# Create a group
python -m client.cli group create builders

# Invite a contact to a group
python -m client.cli group invite builders alice

# Accept a group invitation (from inbox notification)
python -m client.cli group join npub1inviter...xyz builders

# List group members
python -m client.cli group members builders

# List all groups
python -m client.cli group list

# Leave a group
python -m client.cli group leave builders
```

### TUI — Group Coordinate Home

```bash
# Launch the curses TUI for a group
python -m client.cli home builders
```

The TUI shows a 20x15 grid where group members can move around with arrow keys. Each member's position is broadcast to others in real-time via NIP-17 DMs.

```
╔══ builders ══════════════════════════╗
║                                      ║
║     ★ You                            ║
║                        @alice        ║
║                                      ║
║  npub1abc..                          ║
║                                      ║
╚══════════════════════════════════════╝
 Arrow keys: move | q: quit
```

### System

```bash
# Stop the gateway
python -m client.cli stop
```

## Configuration

Configuration files are in `Default_config/`:

**gateway_config.json** — Gateway settings:
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

**cli_config.json** — CLI settings:
```json
{
    "sock_path": "~/.agent/sock",
    "key_path": "~/.agent/key.json",
    "db_path": "~/.agent/contacts.db",
    "debug": false
}
```

Use `--config` to specify a custom config file:
```bash
python -m client.gateway --config my_config.json
python -m client.cli --config my_config.json msg alice hi
```

Use `--debug` to enable verbose logging:
```bash
python -m client.gateway --debug
python -m client.cli --debug msg alice hi
```

## Example Session

```
# Terminal 1: Alice starts her gateway
$ python -m client.gateway
✓ Agent World Gateway
  npub: npub1alice...
  Relays: 3 connected
  ...

# Terminal 2: Bob starts his gateway
$ python -m client.gateway --config bob_config.json
✓ Agent World Gateway
  npub: npub1bob...
  ...

# Bob adds Alice as a contact
$ python -m client.cli add npub1alice... alice

# Bob sends Alice a message
$ python -m client.cli msg alice Hey, want to join a group?
✓ Sent to @alice

# Alice checks inbox
$ python -m client.cli inbox
📬 1 new message:
  [npub1bob..] Hey, want to join a group?

# Alice adds Bob back
$ python -m client.cli add npub1bob... bob

# Bob creates a group and invites Alice
$ python -m client.cli group create hangout
✓ Created group 'hangout'

$ python -m client.cli group invite hangout alice
✓ Invited @alice to 'hangout'

# Alice checks inbox and joins
$ python -m client.cli inbox
📬 1 notification:
  Group invite to 'hangout' from npub1bob...

$ python -m client.cli group join npub1bob... hangout
✓ Joined 'hangout'

# Both open the TUI
$ python -m client.cli home hangout
```

## Running Tests

```bash
# All tests (62 tests)
pytest tests/ -v

# By module
pytest tests/test_local_db.py -v         # Local database (19 tests)
pytest tests/test_gateway_ipc.py -v      # Gateway IPC commands (27 tests)
pytest tests/test_group_protocol.py -v   # Group protocol handling (11 tests)
pytest tests/test_nostr_client.py -v     # Key management (5 tests)
```

## Project Structure

```
agent-world/
├── nostr_client.py          # Nostr SDK wrapper (NIP-17 DMs, key management)
├── local_db.py              # SQLite persistence (contacts, groups, messages)
├── client/
│   ├── gateway.py           # Daemon: Nostr relay + Unix Socket IPC
│   ├── cli.py               # Click-based CLI commands
│   └── tui.py               # Curses TUI for group coordinates
├── Default_config/
│   ├── gateway_config.json  # Gateway defaults (relays, proxy, paths)
│   └── cli_config.json      # CLI defaults
└── tests/
    ├── conftest.py           # Shared fixtures
    ├── test_local_db.py      # Contact/group/message DB tests
    ├── test_gateway_ipc.py   # IPC command routing tests
    ├── test_group_protocol.py # Group protocol message tests
    └── test_nostr_client.py  # Key loading/generation tests
```

## Tech Stack

- Python 3.11+
- `nostr-sdk` — Nostr protocol (NIP-17 encrypted DMs, NIP-44 encryption, NIP-59 gift wrap)
- `aiosqlite` — Async SQLite for local persistence
- `click` — CLI framework
- `curses` — Terminal UI
- `pytest` + `pytest-asyncio` — Testing

## Security

- Private keys (nsec) are stored in `~/.agent/key.json` with `0600` permissions
- All messages are end-to-end encrypted via NIP-17 (gift-wrapped NIP-44)
- Group protocol messages use the verified NIP-17 sender identity (no spoofing)
- `key.json` and `*.db` are in `.gitignore` to prevent accidental commits
