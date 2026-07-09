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

def http_handshake(reader, writer, headers):
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


def read_frame(reader):
    pass

def write_frame(writer, data, opcode):
    pass

def handle(reader, writer):
    pass

def main():
    pass