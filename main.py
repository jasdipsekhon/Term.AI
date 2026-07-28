import asyncio
import os
import signal
import time
from mcp_server import mcp
from web.web_socket import start_web_socket_server

PIDFILE = os.path.join(os.environ.get("LOCALAPPDATA", "."), "Term.AI", "server.pid")


def _kill_stale_instance():
    if not os.path.exists(PIDFILE):
        return
    try:
        with open(PIDFILE) as f:
            old_pid = int(f.read().strip())
    except (ValueError, OSError):
        return
    if old_pid == os.getpid():
        return
    try:
        os.kill(old_pid, signal.SIGTERM)
        time.sleep(1)
    except OSError:
        pass


def _write_pidfile():
    try:
        os.makedirs(os.path.dirname(PIDFILE), exist_ok=True)
        with open(PIDFILE, "w") as f:
            f.write(str(os.getpid()))
    except OSError:
        pass


async def main():
    web_task = asyncio.create_task(start_web_socket_server())
    mcp_task = asyncio.create_task(mcp.run_stdio_async())
    try:
        await mcp_task
    finally:
        if not web_task.done():
            web_task.cancel()
            try:
                await web_task
            except (asyncio.CancelledError, Exception):
                pass


def run():
    _kill_stale_instance()
    _write_pidfile()
    asyncio.run(main())


if __name__ == "__main__":
    run()
