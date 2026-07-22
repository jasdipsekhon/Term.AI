import asyncio
from ssh_session import SSHSession

ssh_session = None # The current active SSH session
_host = None
_username = None
_lock = asyncio.Lock()
ssh_session_changed = asyncio.Event() 


def notifyssh_session_changed():
    global ssh_session_changed
    ssh_session_changed.set()
    ssh_session_changed = asyncio.Event()


def _make_disconnect_handler(session):
    def handler():
        global ssh_session, _host, _username
        if ssh_session is session:
            ssh_session = None
            _host = None
            _username = None
            notifyssh_session_changed()
    return handler


async def openssh_session(host, username, password):
    global ssh_session, _host, _username
    async with _lock:
        if ssh_session is not None:
            try:
                await ssh_session.close()
            except Exception:
                pass
            ssh_session = None
        try:
            newssh_session = SSHSession(host, username, password)
            await newssh_session.start_ssh_client()
            newssh_session.ssh_client.on_disconnect = _make_disconnect_handler(newssh_session)
            ssh_session = newssh_session
            _host = host
            _username = username
            notifyssh_session_changed()
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "reason": str(e)}
