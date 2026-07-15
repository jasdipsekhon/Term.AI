import asyncio
import hashlib
import base64
import json
import struct
import session_state

"""
Flow:
1. TCP connection from the client (browser) arrives at the asyncio server.
2. Read HTTP headers
3. Compute accept key, send 101
4. Loop: read frames, write frames to the client
"""
magic_UUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

def http_handshake(headers):
    # 1. Read the Sec-WebSocket-Key from the HTTP headers
    # 2. Concatenate it with the magic UUID
    # 3. SHA1 hash that string
    # 4. Base64 encode the hash
    # 5. Send back an HTTP 101 response with that value as Sec-WebSocket-Accept
   sec_websocket_key_with_UUID = headers.get("Sec-WebSocket-Key") + magic_UUID
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
    if length == 126:
        buf = await reader.readexactly(2)
        length = buf[0] << 8 | buf[1]
    elif length == 127:
        buf = await reader.readexactly(8)
        length = buf[0] << 56 | buf[1] << 48 | buf[2] << 40 | buf[3] << 32 | buf[4] << 24 | buf[5] << 16 | buf[6] << 8 | buf[7]
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
    while n:
        buf += bytearray(data)
        n-=1
    writer.write(buf)

def _handle():
    pass

def start_web_socket_server(reader, writer):
    pass

async def main():
    server = await asyncio.start_server(_handle, "127.0.0.1", 8765)
    async with server:
        await server.serve_forever()