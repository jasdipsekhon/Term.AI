# Architecture

A terminal that a human drives normally, with Claude attached over MCP + SSH as
an invited participant. Claude can be asked a question in plain English, take
the keyboard, run a sequence of commands to probe a device, and hand control
back — while the human watches live and can take over at any instant.

## System overview

```
        You ask in chat                 You watch & type
              |                                |
              v                                v
   +----------------------+        +----------------------+
   | Claude Desktop (chat) |        |  Browser viewer       |
   |   Claude-facing       |        |  xterm.js, human-facing|
   +----------+-----------+        +-----------+----------+
              | MCP (stdio)                     | HTTP (static page)
              v                                 | WebSocket (live terminal)
   +======================================================+
   |  MCP server + web server  —  local Python process     |
   |                                                        |
   |  +-----------+   +------------------+   +-----------+  |
   |  | MCP tools |-->| SSHSession       |<->| WebSocket |  |
   |  | Claude    |   | pyte ·           |   | single    |  |
   |  | calls     |   | idle detection   |   | subscriber|  |
   |  |           |   |                  |   |           |  |
   |  +-----------+   +--------+---------+   +-----------+  |
   +===========================|============================+
                               | SSH
                               v
                  +-------------------------+
                  |  SSHClient (asyncssh)   |
                  +-----------+-------------+
                              |
                              v
                     +-----------------+
                     |  Target device   |
                     +-----------------+
```

## Core principle: one PTY, two emulators

A single PTY is the source of truth. Its raw output byte stream is fed to two
terminal emulators that serve different readers:

- **pyte** (headless, in the Python process) renders the stream to clean
  screen-text — this is what Claude reads.
- **xterm.js** (in the browser) renders the stream to a live visual terminal —
  this is what the human sees.

They never diverge because both emulate the *same output bytes*. Only *input*
has to be coordinated — both Claude (via MCP tools) and the human (via the
browser) call `SSHSession.write()` directly; there is no arbitration layer.

## Components

| File | Role |
|------|------|
| `ssh_session.py` | `SSHSession` core: pyte emulation (`HistoryScreen`), output notification to the connected browser subscriber, idle done-detection |
| `ssh_client.py` | asyncssh-based SSH transport with PTY allocation and resize support |
| `mcp_server.py` | FastMCP server exposing the MCP tools |
| `session_facade.py` | Shared `SSHSession` reference, disconnect handler, and session-change event used by both MCP tools and web server |
| `web/web_socket.py` | Bare-metal asyncio TCP server — implements WebSocket protocol (RFC 6455) manually; serves the static viewer page over plain HTTP and streams terminal bytes over the WebSocket upgrade on the same port |
| `web/static/index.html` | xterm.js browser viewer: renders output, sends keystrokes, sends resize events |
| `main.py` | Entry point — runs MCP server (stdio) and web server (port 8765) concurrently |
| `configure.py` | One-time setup script — writes the MCP server entry into Claude Desktop's `claude_desktop_config.json` |

Claude Desktop is the chat front end and the MCP host.

## The tools Claude calls

| Tool | Purpose |
|------|---------|
| `open_session` | Open an SSH session to a remote device |
| `write_and_read_response` | Send a shell command and return its output |
| `session_status` | Check whether a session is currently active (host, username) |

## Request lifecycle

1. You type a request in Claude Desktop.
2. Claude calls `open_session` → `session_facade.open_ssh_session` creates an
   `SSHSession`, calls `SSHSession.start_ssh_client()`, and stores the session
   in `session_facade.ssh_session`. A `notify_ssh_session_changed()` fires so
   any connected browser tab reconnects.
3. Output splits: `SSHSession._on_data` feeds raw bytes into pyte (updates the
   screen Claude reads) and notifies the connected browser subscriber (live view).
4. Claude calls `write_and_read_response` — records the current line count, writes
   the command, waits for idle (no screen change for 0.3 s), then reads everything
   since the recorded line via `get_output_since`.
5. If you type in the viewer, your keystrokes go through the WebSocket directly
   to `SSHSession.write()` alongside Claude's writes — no priority mechanism.

## Browser session flow

The MCP tools and the browser viewer share one session object via `session_facade`.
When a new session is created or the SSH connection drops, `session_facade.ssh_session_changed`
fires; the WebSocket handler closes the connection and the viewer reconnects, picking up
whichever session is current.

## Key design decisions

- **Single source of truth.** One SSH PTY; both emulators are read-only
  projections of its output.
- **Idle done-detection.** `wait_until_idle` polls every 50 ms and returns when
  the screen buffer stops changing for 0.3 s. Works for interactive programs
  (`top`, `vim`, REPLs) that a sentinel can't handle. Timeout is configurable
  per-call.
- **History-aware output capture.** `SSHSession` uses `pyte.HistoryScreen`
  (10 000-line scrollback). `get_output_since(line_index)` concatenates history
  and visible lines so Claude sees output that has already scrolled off screen.
- **Stdout isolation.** All logging goes to stderr so nothing corrupts the MCP JSON-RPC channel on stdout.
- **Session-change eventing.** `session_facade.ssh_session_changed` is an
  `asyncio.Event` that is replaced (not just set) on each change, so the WebSocket
  handler can wait on it without missing back-to-back transitions.
- **Reconnect over migrate.** On a session change the WebSocket handler closes
  the connection rather than trying to hand it off mid-stream; the browser's
  own reconnect logic picks up the new (or absent) session a moment later.
  Simpler than migration, and the disruption is rare in practice.

## Known limitations

- **Credentials pass through the MCP boundary.** `open_session(host, username, password)`
  sends the password as a tool argument, so it is visible in the Claude conversation
  and Claude Desktop's logs. There is no local credential store yet.
- **No WebSocket authentication.** Any local process that can reach `127.0.0.1:8765`
  can open the viewer connection and drive the session. Binding to loopback blocks
  remote access but not other local processes or browser tabs.
- **Host key verification is disabled.** `ssh_client.py` connects with `known_hosts=None`,
  so a network attacker could impersonate the target device.

## Operating modes

- **Headless** — chat only, no viewer. Claude probes the device and reports
  back via `write_and_read_response`.
- **Co-pilot** — chat + the browser viewer at `http://127.0.0.1:8765`. Watch live
  and type alongside Claude.

## Status

Verified end to end: all three MCP tools register; Claude opens SSH session →
runs commands → idle detection fires → viewer receives live bytes → browser resize
events propagate to the PTY.
