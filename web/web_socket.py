import asyncio
import hashlib
import base64
import json
import sys
from pathlib import Path
import session_facade as session_state

"""
Flow:
1. TCP connection from the client (browser) arrives at the asyncio server.
2. Read HTTP headers
3. If Sec-WebSocket-Key is present, compute accept key, send 101, loop on frames.
   Otherwise, serve a static file (the browser viewer) as a plain HTTP response.
"""
RECV_BUF = 4096
TWO_BYTE_LENGTH_FIELD = 126
EIGHT_BYTE_LENGTH_FIELD = 127
MAX_FRAME_SIZE = 16 * 1024 * 1024  # 16 MB cap

magic_UUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

STATIC_DIR = (Path(__file__).parent / "static").resolve()
CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript",
    ".css": "text/css",
}

def http_static_response(path):
    if path == "/":
        path = "/index.html"
    path = path.split("?", 1)[0]
    file_path = (STATIC_DIR / path.lstrip("/")).resolve()
    if STATIC_DIR != file_path and STATIC_DIR not in file_path.parents:
        return b"HTTP/1.1 403 Forbidden\r\n\r\n"
    if not file_path.is_file():
        return b"HTTP/1.1 404 Not Found\r\n\r\n"
    content_type = CONTENT_TYPES.get(file_path.suffix, "application/octet-stream")
    body = file_path.read_bytes()
    header = (
        "HTTP/1.1 200 OK\r\n"
        f"Content-Type: {content_type}\r\n"
        f"Content-Length: {len(body)}\r\n"
        "Connection: close\r\n\r\n"
    ).encode()
    return header + body

def http_handshake(headers):
    # 1. Read the Sec-WebSocket-Key from the HTTP headers
    # 2. Concatenate it with the magic UUID
    # 3. SHA1 hash that string
    # 4. Base64 encode the hash
    # 5. Send back an HTTP 101 response with that value as Sec-WebSocket-Accept
    # Returns None if this is not a WebSocket upgrade (no key present).
    sec_websocket_key = headers.get("Sec-WebSocket-Key")
    if sec_websocket_key is None:
        return None
    sec_websocket_key_with_UUID = sec_websocket_key + magic_UUID
    hash_object = hashlib.sha1(sec_websocket_key_with_UUID.encode('utf-8'))
    base64_encoded_hash = base64.b64encode(hash_object.digest()).decode('utf-8')
    return (
        "HTTP/1.1 101 Switching Protocols\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Accept: {base64_encoded_hash}\r\n\r\n"
    ).encode()

# WebSocket frame layout (big endian):
#
# byte 0:       bit 7 = FIN, bits 6-4 = RSV1-3 (ignore), bits 3-0 = opcode
# byte 1:       bit 7 = MASK, bits 6-0 = payload length (7 bits, value 0-127)
#
# if payload length == 0-125:
#   byte 2-5:   masking key (if MASK=1)
#   byte 2+:    payload data (or byte 6+ if masked)
#
# if payload length == 126:
#   byte 2-3:   real payload length as uint16
#   byte 4-7:   masking key (if MASK=1)
#   byte 8+:    payload data
#
# if payload length == 127:
#   byte 2-9:   real payload length as uint64
#   byte 10-13: masking key (if MASK=1)
#   byte 14+:   payload data
#
# opcodes: 0x1 = text, 0x2 = binary, 0x8 = close, 0x9 = ping, 0xA = pong
#
# client -> server: always masked
# server -> client: never masked

async def read_frame(reader):
    header = await reader.readexactly(2)
    opcode = header[0] & 0x0F 
    mask = (header[1] >> 7) & 1
    length = header[1] & 0x7F
    if length == TWO_BYTE_LENGTH_FIELD:
        buf = await reader.readexactly(2)
        length = buf[0] << 8 | buf[1]
    elif length == EIGHT_BYTE_LENGTH_FIELD:
        buf = await reader.readexactly(8)
        length = buf[0] << 56 | buf[1] << 48 | buf[2] << 40 | buf[3] << 32 | buf[4] << 24 | buf[5] << 16 | buf[6] << 8 | buf[7]
    if length > MAX_FRAME_SIZE:
        raise ValueError(f"frame too large: {length} bytes")
    if mask:
        masking_key = await reader.readexactly(4)
        payload = bytearray(await reader.readexactly(length))
        for i in range(len(payload)):
            payload[i] ^= masking_key[i % 4]
    else:
        payload = bytearray(await reader.readexactly(length))
    return opcode, bytes(payload)

def write_frame(writer, data, opcode):
    buf = bytearray()
    buf.append(0x80 | opcode)
    n = len(data)
    if n < TWO_BYTE_LENGTH_FIELD:
        buf.append(n)
    elif n <= 0xFFFF:
        buf.append(TWO_BYTE_LENGTH_FIELD)
        buf.append(n >> 8 & 0xFF)
        buf.append(n & 0xFF)
    else:
        buf.append(EIGHT_BYTE_LENGTH_FIELD)
        i = 56
        while i >= 0:
            buf.append((n >> i) & 0xFF)
            i -= 8
    buf += data
    writer.write(buf)

async def _parse_http_header(reader):
    http_bytes = b""
    while b"\r\n\r\n" not in http_bytes:
        buf = await reader.read(RECV_BUF)
        if not buf:  # EOF — client disconnected before completing the header
            raise asyncio.IncompleteReadError(http_bytes, None)
        http_bytes += buf
    http_header = http_bytes.split(b"\r\n\r\n", 1)[0]
    http_header_str = http_header.decode("utf-8", errors="replace")
    lines = http_header_str.split("\r\n")
    request_path = lines[0].split(" ")[1] if len(lines[0].split(" ")) >= 2 else "/"
    headers = {}
    for line in lines[1:]:
        if ": " in line:
            key, value = line.split(": ", 1)
            headers[key] = value
    return request_path, headers

async def wait_first(tasks):
    first_completed_task, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    for task in pending:
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass
    return first_completed_task

async def _do_handshake(reader, writer):
    path, headers = await _parse_http_header(reader)
    response = http_handshake(headers)
    if response is None:
        writer.write(http_static_response(path))
        await writer.drain()
        return False
    writer.write(response)
    await writer.drain()
    return True

async def _handle_client_frame(session, opcode, payload, writer):
    if opcode == 0x8:
        return False
    if opcode == 0x1:
        msg = json.loads(payload)
        if msg.get('type') == 'resize':
            await session.resize(msg['cols'], msg['rows'])
    elif opcode == 0x2:
        await session.write(payload)
    elif opcode == 0x9:
        write_frame(writer, payload, 0xA)
    return True

async def tcp_connection_callback(reader, writer):
    session = None

    def on_ssh_output(data, ctx):
        write_frame(writer, data, 0x2)

    try:
        if not await _do_handshake(reader, writer):
            return
        session = session_state.ssh_session
        if session is None:
            write_frame(writer, b"", 0x8)
            await writer.drain()
            return
        session.subscribe(on_ssh_output)
        while True:
            session_changed = session_state.ssh_session_changed
            read_task = asyncio.create_task(read_frame(reader))
            changed_task = asyncio.create_task(session_changed.wait())
            first_completed_task = await wait_first([read_task, changed_task])
            if changed_task in first_completed_task:
                break
            opcode, payload = read_task.result()
            if not await _handle_client_frame(session, opcode, payload, writer):
                break
    except asyncio.IncompleteReadError:
        pass
    except Exception as e:
        print(f"Error reading frame: {e}", file=sys.stderr, flush=True)
    finally:
        if session is not None:
            session.unsubscribe(on_ssh_output)
        writer.close()

async def start_web_socket_server():
    server = await asyncio.start_server(tcp_connection_callback, "127.0.0.1", 8765)
    async with server:
        await server.serve_forever()

    