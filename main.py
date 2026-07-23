import asyncio
from mcp_server import mcp
from web.web_socket import start_web_socket_server


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
    asyncio.run(main())


if __name__ == "__main__":
    run()
