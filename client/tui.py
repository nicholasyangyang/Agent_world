"""
TUI for group Home — curses-based coordinate grid.
Arrow keys to move, q to quit. Positions broadcast via NIP-17.
"""
import asyncio
import curses
import json
import sys
from pathlib import Path

GRID_W = 20
GRID_H = 15


class TUIState:
    def __init__(self, group: str, own_npub: str = "you"):
        self.group = group
        self.own_npub = own_npub
        self.my_x = GRID_W // 2
        self.my_y = GRID_H // 2
        self.positions: dict[str, tuple[int, int]] = {}  # npub -> (x, y)
        self.names: dict[str, str] = {}  # npub -> display name
        self.debug_lines: list[str] = []


def draw(stdscr, state: TUIState):
    """Render the grid to the screen."""
    stdscr.erase()
    h, w = stdscr.getmaxyx()

    # Title
    title = f" 🏠 {state.group} "
    stdscr.addstr(0, 0, "┌" + title + "─" * max(0, w - len(title) - 2) + "┐")

    # Grid area
    grid_top = 1
    grid_bottom = min(grid_top + GRID_H + 1, h - 4)

    # Build grid
    grid = {}
    for npub, (x, y) in state.positions.items():
        name = state.names.get(npub, npub[:10] + "..")
        grid[(x, y)] = name
    grid[(state.my_x, state.my_y)] = "★ You"

    for row in range(grid_top, grid_bottom):
        gy = row - grid_top
        line = "│"
        col = 1
        placed = {}
        # Find entities on this row
        for (ex, ey), name in grid.items():
            if ey == gy:
                placed[ex] = name

        # Render row
        row_str = " " * (w - 2)
        row_chars = list(row_str)
        for ex, name in placed.items():
            pos = min(ex * 3, len(row_chars) - len(name) - 1)
            pos = max(0, pos)
            label = name[:w - 4]
            for i, ch in enumerate(label):
                if pos + i < len(row_chars):
                    row_chars[pos + i] = ch

        line += "".join(row_chars)
        line = line[:w - 1] + "│"
        try:
            stdscr.addstr(row, 0, line[:w])
        except curses.error:
            pass

    # Status bar
    status_y = grid_bottom
    members = len(state.positions) + 1
    status = f"│ ←↑↓→: move │ q: quit │ Pos: ({state.my_x},{state.my_y}) │ Members: {members} "
    separator = "├" + "─" * (w - 2) + "┤"
    bottom = "└" + "─" * (w - 2) + "┘"

    try:
        stdscr.addstr(status_y, 0, separator[:w])
        stdscr.addstr(status_y + 1, 0, (status + " " * max(0, w - len(status) - 1) + "│")[:w])
        if state.debug_lines:
            for i, dline in enumerate(state.debug_lines[-2:]):
                if status_y + 2 + i < h - 1:
                    dbg = f"│ [D] {dline}"
                    stdscr.addstr(status_y + 2 + i, 0, (dbg + " " * max(0, w - len(dbg) - 1) + "│")[:w])
        if status_y + 4 < h:
            stdscr.addstr(min(status_y + 4, h - 1), 0, bottom[:w])
    except curses.error:
        pass

    stdscr.refresh()


async def ipc_send(sock_path: str, cmd: str, args: dict) -> dict:
    """Send a single IPC command and get response."""
    reader, writer = await asyncio.open_unix_connection(sock_path)
    req = json.dumps({"cmd": cmd, "args": args}) + "\n"
    writer.write(req.encode())
    await writer.drain()
    raw = await reader.readline()
    writer.close()
    await writer.wait_closed()
    return json.loads(raw.decode())


async def ipc_subscribe(sock_path: str, group: str):
    """Open a streaming IPC connection for group events."""
    reader, writer = await asyncio.open_unix_connection(sock_path)
    req = json.dumps({"cmd": "group_subscribe", "args": {"group": group}}) + "\n"
    writer.write(req.encode())
    await writer.drain()
    # Read initial ack
    ack = await reader.readline()
    return reader, writer


async def tui_main(stdscr, group: str, sock_path: str, debug: bool):
    """Main TUI event loop."""
    stdscr.nodelay(True)
    stdscr.keypad(True)
    curses.curs_set(0)

    state = TUIState(group)

    # Get own npub
    try:
        resp = await ipc_send(sock_path, "whoami", {})
        state.own_npub = resp.get("output", "?")
    except Exception:
        pass

    # Get group members for initial display name resolution
    try:
        resp = await ipc_send(sock_path, "group_members", {"group": group})
    except Exception:
        pass

    # Subscribe to group events
    sub_reader = None
    sub_writer = None
    try:
        sub_reader, sub_writer = await ipc_subscribe(sock_path, group)
    except Exception as e:
        state.debug_lines.append(f"Subscribe failed: {e}")

    # Send initial position
    try:
        await ipc_send(sock_path, "group_position", {
            "group": group, "x": state.my_x, "y": state.my_y
        })
    except Exception:
        pass

    draw(stdscr, state)

    running = True
    while running:
        # Handle keyboard input
        try:
            key = stdscr.getch()
        except Exception:
            key = -1

        moved = False
        if key == ord('q') or key == ord('Q'):
            running = False
            break
        elif key == curses.KEY_UP and state.my_y > 0:
            state.my_y -= 1
            moved = True
        elif key == curses.KEY_DOWN and state.my_y < GRID_H - 1:
            state.my_y += 1
            moved = True
        elif key == curses.KEY_LEFT and state.my_x > 0:
            state.my_x -= 1
            moved = True
        elif key == curses.KEY_RIGHT and state.my_x < GRID_W - 1:
            state.my_x += 1
            moved = True

        if moved:
            try:
                await ipc_send(sock_path, "group_position", {
                    "group": group, "x": state.my_x, "y": state.my_y
                })
            except Exception as e:
                if debug:
                    state.debug_lines.append(f"Send pos err: {e}")

        # Check for incoming events from subscription
        if sub_reader:
            try:
                # Non-blocking read
                line = await asyncio.wait_for(sub_reader.readline(), timeout=0.05)
                if line:
                    event = json.loads(line.decode())
                    evt_type = event.get("type", "")
                    npub = event.get("npub", "")

                    if evt_type == "position" and npub != state.own_npub:
                        state.positions[npub] = (event.get("x", 0), event.get("y", 0))
                        if npub not in state.names:
                            state.names[npub] = npub[:10] + ".."
                        if debug:
                            state.debug_lines.append(
                                f"Pos: {state.names[npub]} → ({event['x']},{event['y']})"
                            )
                    elif evt_type == "leave":
                        state.positions.pop(npub, None)
                        state.names.pop(npub, None)
                        if debug:
                            state.debug_lines.append(f"Left: {npub[:10]}")

            except asyncio.TimeoutError:
                pass
            except Exception as e:
                if debug:
                    state.debug_lines.append(f"Recv err: {e}")

        draw(stdscr, state)
        await asyncio.sleep(0.05)

    # Cleanup
    if sub_writer:
        try:
            sub_writer.close()
        except Exception:
            pass


def run_tui(group: str, sock_path: str, debug: bool = False):
    """Entry point: run the curses TUI."""
    def _curses_wrapper(stdscr):
        asyncio.run(tui_main(stdscr, group, sock_path, debug))

    curses.wrapper(_curses_wrapper)
