import asyncio
from session import Session

_session = None # The current active SSH session
_host = None
_username = None
_lock = asyncio.Lock()
_session_changed = asyncio.Event() 


def notify_session_changed():
    global _session_changed
    _session_changed.set()
    _session_changed = asyncio.Event()


def _make_disconnect_handler(session):
    def handler():
        global _session, _host, _username
        if _session is session:
            _session = None
            _host = None
            _username = None
            notify_session_changed()
    return handler


async def open_session(host, username, password):
    global _session, _host, _username
    async with _lock:
        if _session is not None:
            try:
                await _session.close()
            except Exception:
                pass
            _session = None
        try:
            new_session = Session(host, username, password)
            await new_session.start_ssh_client()
            new_session.ssh_client.on_disconnect = _make_disconnect_handler(new_session)
            _session = new_session
            _host = host
            _username = username
            notify_session_changed()
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "reason": str(e)}
