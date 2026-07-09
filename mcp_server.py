from mcp.server.fastmcp import FastMCP
import session_state

mcp = FastMCP("Term.AI")


@mcp.tool()
async def open_session(host: str, username: str, password: str):
    """Open an SSH session to a remote device. Must be called before any other tool.
    Only one session is active at a time — calling this again closes the current one and opens a new one.
    Args:
        host: hostname or IP address of the remote device (e.g. "192.168.1.1").
        username: SSH login username.
        password: SSH password for the user.

    Returns {"ok": True} on success, or {"ok": False, "reason": "..."} on failure.
    On failure, no session is open — check credentials and retry before calling other tools.
    """
    return await session_state.open_session(host, username, password)


@mcp.tool()
async def write_and_read_response(text: str, timeout: float = 60.0):
    """Send text to the active SSH session and return the shell output.
    Requires an open session — call open_session first.
    A newline is appended automatically — do not include one in text.
    Args:
        text: command or input to send (e.g. "ls -la", "yes", "q"). Do not add a trailing newline.
        timeout: seconds to wait for output to settle. Default 60. Increase for slow commands (e.g. 300 for installs or scans).

    Returns {"ok": True, "output": "...", "timed_out": bool} on success,
    or {"ok": False, "reason": "..."} if the session is closed or write fails.
    timed_out is True if output did not settle within timeout seconds.
    If timed_out is True and the command is hanging, call this tool with text="\x03" (Ctrl+C / ETX) to interrupt it.
    For interactive prompts (sudo password, y/n confirmations), send just the response as text.
    """
    ssh_session = session_state._session
    if ssh_session is None:
        return {"ok": False, "reason": "No active SSH session"}
    try:
        output_start_line_index = ssh_session.line_count()
        await ssh_session.write((text + "\n").encode())
        result = await ssh_session.wait_until_idle(timeout_s=timeout)
        timed_out = not result["done"]
        output = ssh_session.get_output_since(output_start_line_index).strip()
        return {"ok": True, "output": output, "timed_out": timed_out}
    except Exception as e:
        return {"ok": False, "reason": str(e)}


@mcp.tool()
async def session_status():
    """Check whether an SSH session is currently active.

    Returns {"active": True, "host": "...", "username": "..."} if connected,
    or {"active": False} if no session is open.
    Call this before write_and_read_response if unsure whether a session exists.
    """
    if session_state._session is None:
        return {"active": False}
    return {"active": True, "host": session_state._host, "username": session_state._username}


if __name__ == "__main__":
    mcp.run()
