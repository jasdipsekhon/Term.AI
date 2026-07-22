import asyncio
from mcp_server import mcp
from web.web_socket import start_web_socket_server


async def main():
    web_task = asyncio.create_task(start_web_socket_server())
    mcp_task = asyncio.create_task(mcp.run_stdio_async())
    try:
        await asyncio.wait([web_task, mcp_task], return_when=asyncio.FIRST_COMPLETED)
    finally:
        for task in (web_task, mcp_task):
            if not task.done():
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass


def run():
    asyncio.run(main())


if __name__ == "__main__":
    run()
