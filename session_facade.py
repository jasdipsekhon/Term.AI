import asyncio
from ssh_session import SSHSession

# Facade over SSHSession. One PTY (one SSH connection) is held in ssh_session.
# Both MCP and WebSocket reach the same PTY through this shared reference.

ssh_session = None # The current active SSH session
_host = None
_username = None
_lock = asyncio.Lock()
ssh_session_changed = asyncio.Event() 


def notify_ssh_session_changed():
    global ssh_session_changed
    ssh_session_changed.set()
    ssh_session_changed = asyncio.Event()


def status():
    if ssh_session is None:
        return {"active": False}
    return {"active": True, "host": _host, "username": _username}


async def open_ssh_session(host, username, password):
    global ssh_session, _host, _username
    async with _lock:
        if ssh_session is not None:
            ssh_session.ssh_client.on_disconnect = None
            try:
                await ssh_session.close()
            except Exception:
                pass
            ssh_session = None
        try:
            new_ssh_session = SSHSession(host, username, password)
            await new_ssh_session.start_ssh_client()

            def on_disconnect():
                global ssh_session, _host, _username
                if ssh_session is new_ssh_session:
                    ssh_session = None
                    _host = None
                    _username = None
                    notify_ssh_session_changed()

            new_ssh_session.ssh_client.on_disconnect = on_disconnect
            ssh_session = new_ssh_session
            _host = host
            _username = username
            notify_ssh_session_changed()
            return {"ok": True}
        except Exception as e:
            notify_ssh_session_changed()
            return {"ok": False, "reason": str(e)}
