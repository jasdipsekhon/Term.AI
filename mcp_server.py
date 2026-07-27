from mcp.server.fastmcp import FastMCP
import session_facade

mcp = FastMCP("Term.AI", instructions="AI-assisted SSH terminal — share a live shell with Claude")

MAX_OUTPUT_CHARS = 20_000


@mcp.tool()
async def open_session(host: str, username: str, password: str):
    """Open an SSH session to a remote device. Must be called before any other tool.
    Only one session is active at a time — calling this again closes the current one and opens a new one.
    Args:
        host: hostname or IP address of the remote device (e.g. "192.168.1.1").
        username: SSH login username.
        password: SSH password for the user.

    Returns {"ok": True} on success, or {"ok": False, "reason": "..."} on failure.
    On failure, any existing session is left untouched and still usable — this only replaces
    it once the new connection actually succeeds.
    """
    return await session_facade.open_ssh_session(host, username, password)


@mcp.tool()
async def write_and_read_response(text: str, timeout: float = 60.0):
    """Send text to the active SSH session and return the shell output.
    Requires an open session — call open_session first.
    A newline is appended automatically — do not include one in text.
    Args:
        text: command or input to send (e.g. "ls -la", "yes", "q"). Do not add a trailing newline.
            Pass "" to poll for output from a still-running command without sending anything.
        timeout: seconds to wait for output to settle. Default 60. Increase for slow commands (e.g. 300 for installs or scans).

    Returns {"ok": True, "output": "...", "timed_out": bool} on success,
    or {"ok": False, "reason": "..."} if the session is closed or write fails.
    timed_out is True if output did not settle within timeout seconds. For a command that stays
    silent for a while (e.g. "sleep 30"), this can report timed_out=True even though it's still
    running -- call again with text="" to poll for output without sending anything new.
    If timed_out is True and the command is hanging, call this tool with text="\x03" (Ctrl+C / ETX) to interrupt it.
    For interactive prompts (sudo password, y/n confirmations), send just the response as text.
    Output longer than 20,000 characters is truncated, keeping the most recent output.
    """
    session = session_facade.ssh_session
    if session is None:
        return {"ok": False, "reason": "No active SSH session"}
    try:
        # Anchor to where the last call left off, not to "now" -- output that streams in
        # between calls (while the caller is doing something else) must not be skipped.
        output_start_line_index = session.last_read_line
        if text == "":
            to_send = None
        elif text.isprintable():
            to_send = text + "\n"
        else:
            to_send = text
        if to_send is not None:
            await session.write(to_send.encode())
        result = await session.wait_until_idle(timeout_s=timeout)
        if session_facade.ssh_session is not session:
            return {"ok": False, "reason": "Session ended while waiting for output"}
        timed_out = not result["done"]
        output = session.get_output_since(output_start_line_index).strip()
        session.last_read_line = session.line_count()
        if len(output) > MAX_OUTPUT_CHARS:
            omitted = len(output) - MAX_OUTPUT_CHARS
            output = f"[...{omitted} earlier characters truncated...]\n" + output[-MAX_OUTPUT_CHARS:]
        return {"ok": True, "output": output, "timed_out": timed_out}
    except Exception as e:
        return {"ok": False, "reason": str(e)}


@mcp.tool()
async def end_session():
    """Close the active SSH session without opening a new one.
    Disconnects the underlying SSH connection and clears the browser terminal view.

    Returns {"ok": True} on success, or {"ok": False, "reason": "..."} if no session is open.
    """
    return await session_facade.end_session()


@mcp.tool()
async def session_status():
    """Check whether an SSH session is currently active.

    Returns {"active": True, "host": "...", "username": "..."} if connected,
    or {"active": False} if no session is open.
    Call this before write_and_read_response if unsure whether a session exists.
    """
    return session_facade.status()


if __name__ == "__main__":
    mcp.run()
