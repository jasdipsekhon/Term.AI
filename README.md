# Term.AI

Control remote devices over SSH directly from Claude Desktop.

## What it does

Gives Claude Desktop three tools:
- **open_session** — connect to a device via SSH
- **write_and_read_response** — run a command and get the output
- **session_status** — check whether a session is currently active

A live terminal view is available in your browser at `http://127.0.0.1:8765` while a session is open.

## Architecture

`Session` is a facade that combines three components behind a single interface:
- **SSH** — connects to the remote device via asyncssh
- **pyte** — emulates the terminal, tracking what's on screen and in scrollback history
- **WebSocket** — notifies browser subscribers when new output arrives

## Requirements

- Windows 10/11
- [Python 3.10 or later](https://www.python.org/downloads/) — during install, check **"Add Python to PATH"**
- [Claude Desktop](https://claude.ai/download)

## Setup

**1. Download this project**

Download and extract the ZIP, or clone the repo into a folder on your PC.

**2. Run setup**

Double-click `setup.bat`. It installs all dependencies and automatically configures Claude Desktop.

**3. Restart Claude Desktop**

Fully quit (right-click tray icon → Quit) and reopen. Term.AI will appear under Developer settings.

## Usage

In a Claude Desktop chat, ask Claude to connect to your device:

> "Connect to 192.168.1.100 as admin, pw: root, and run whoami."

Use Term.AI MCP server to open an SSH session with 192.168.11.230 as builder, password: root

Claude will use the SSH tools automatically. Open `http://127.0.0.1:8765` in a browser to watch the terminal live.

## Troubleshooting

**Term.AI does not appear in Claude Desktop**
- Make sure you fully quit and restarted Claude Desktop (not just closed the window)
- Check Developer settings — if it shows a red error, open the logs for details

**Connection fails**
- Verify the device is reachable: open a command prompt and run `ping <host>`
- Confirm the username and password are correct
- Ensure SSH is enabled on the remote device
