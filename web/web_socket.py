import asyncio
import hashlib
import base64
import json
import struct
import session_state

magic_UUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


def _ws_handshake(key):
    accept = base64.b64encode(
        hashlib.sha1((key + magic_UUID).encode()).digest()
    ).decode()
    return (
        "HTTP/1.1 101 Switching Protocols\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Accept: {accept}\r\n\r\n"
    ).encode()


def _http_json(body):
    body = json.dumps(body).encode()
    return (
        "HTTP/1.1 200 OK\r\n"
        "Content-Type: application/json\r\n"
        f"Content-Length: {len(body)}\r\n"
        "Connection: close\r\n\r\n"
    ).encode() + body


RECV_BUF = 4096


async def _read_frame(reader):
    header = await reader.readexactly(2)
    opcode  = header[0] & 0x0f
    masked  = bool(header[1] & 0x80)
    length  = header[1] & 0x7f

    if length == 126:
        length = struct.unpack(">H", await reader.readexactly(2))[0]
    elif length == 127:
        length = struct.unpack(">Q", await reader.readexactly(8))[0]

    mask = await reader.readexactly(4) if masked else None
    data = bytearray(await reader.readexactly(length))

    if mask:
        for i in range(len(data)):
            data[i] ^= mask[i % 4]

    return opcode, bytes(data)


def _frame(data, opcode=0x2):
    n = len(data)
    buf = bytearray()
    buf.append(0x80 | opcode)
    if n < 126:
        buf.append(n)
    elif n < 65536:
        buf.append(126)
        buf += struct.pack(">H", n)
    else:
        buf.append(127)
        buf += struct.pack(">Q", n)
    buf += data
    return bytes(buf)


async def _ws_loop(reader, writer, headers):
    writer.write(_ws_handshake(headers.get("Sec-WebSocket-Key", "")))
    await writer.drain()

    session = session_state._session
    if session is None:
        writer.write(_frame(b"", opcode=0x8))
        await writer.drain()
        writer.close()
        return

    closed = False

    async def on_output(data):
        nonlocal closed
        if closed:
            return
        try:
            writer.write(_frame(data))
            await writer.drain()
        except Exception:
            closed = True
            session.unsubscribe(on_output)

    session.subscribe(on_output)
    writer.write(_frame(b"\x1b[2J\x1b[H"))
    await writer.drain()

    try:
        while True:
            changed_event = session_state._session_changed
            recv_task    = asyncio.ensure_future(_read_frame(reader))
            changed_task = asyncio.ensure_future(changed_event.wait())

            done, pending = await asyncio.wait(
                [recv_task, changed_task],
                return_when=asyncio.FIRST_COMPLETED,
            )
            for t in pending:
                t.cancel()

            if changed_task in done:
                closed = True
                session.unsubscribe(on_output)
                session = session_state._session
                closed = False
                if session is None:
                    break
                session.subscribe(on_output)
                writer.write(_frame(b"\x1b[2J\x1b[H"))
                await writer.drain()
                continue

            opcode, data = recv_task.result()
            if opcode == 0x8:
                break
            if opcode == 0x2:
                await session.write(data, sender="human")
            elif opcode == 0x1:
                try:
                    msg = json.loads(data)
                    if msg.get("type") == "resize":
                        await session.resize(msg["cols"], msg["rows"])
                except (json.JSONDecodeError, KeyError):
                    pass
    except Exception:
        pass
    finally:
        closed = True
        session.unsubscribe(on_output)
        writer.close()


async def _handle(reader, writer):
    try:
        raw = b""
        while b"\r\n\r\n" not in raw:
            chunk = await reader.read(RECV_BUF)
            if not chunk:
                writer.close()
                return
            raw += chunk

        head, leftover = raw.split(b"\r\n\r\n", 1)
        lines = head.decode(errors="replace").split("\r\n")
        headers = {}
        for line in lines[1:]:
            if ": " in line:
                k, v = line.split(": ", 1)
                headers[k] = v

        if headers.get("Upgrade", "").lower() == "websocket":
            await _ws_loop(reader, writer, headers)
        else:
            n = int(headers.get("Content-Length", 0))
            while len(leftover) < n:
                leftover += await reader.read(n - len(leftover))
            body = json.loads(leftover)
            result = await session_state.open_session(body["host"], body["username"], body["password"])
            writer.write(_http_json(result))
            await writer.drain()
            writer.close()
    except Exception:
        writer.close()


async def start_server():
    server = await asyncio.start_server(_handle, "127.0.0.1", 8765)
    async with server:
        await server.serve_forever()
