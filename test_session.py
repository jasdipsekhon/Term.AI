import asyncio
import unittest
from unittest.mock import MagicMock, AsyncMock, patch
from ssh_session import SSHSession
from web.web_socket import read_frame, write_frame
import session_facade
import mcp_server
import web.web_socket as web_socket
from ssh_client import _clean_os_error_message


def make_session():
    return SSHSession("host", "user", "pass")

class TestWebSocketReadFrameUnmasked(unittest.IsolatedAsyncioTestCase):
    async def test_read_frame(self):
        # 1000 0001, 0000 0101
        reader = asyncio.StreamReader()
        payload = b"hello"
        frame = bytearray([0x81, len(payload)]) + payload
        reader.feed_data(frame)
        self.assertEqual(await read_frame(reader), (0x1, payload))

class TestWebSocketReadFrameMasked(unittest.IsolatedAsyncioTestCase):
    # bytes = const uint8_t[]
    # bytearray = uint8_t[]
    async def test_read_frame(self):
        # 1000 0001, 1000 0101
        reader = asyncio.StreamReader()
        payload = b"hello"
        mask = b'\x01\x02\x03\x04'
        mutable_payload = bytearray(payload)
        for i in range(len(mutable_payload)):
            mutable_payload[i] ^= mask[i % 4]
        frame = bytearray([0x81, 0x80 | len(payload)]) + mask + mutable_payload
        reader.feed_data(frame)
        self.assertEqual(await read_frame(reader), (0x1, payload))

class TestWebSocketWriteFrame(unittest.IsolatedAsyncioTestCase):
    async def test_write_frame(self):
        # 1000 0001, 0000 0101
        from unittest.mock import MagicMock
        writer = MagicMock()
        payload = b"hello"
        write_frame(writer, payload, 0x1)
        frame = writer.write.call_args[0][0]
        expected = bytearray([0x81, len(payload)]) + payload
        self.assertEqual(frame, expected)
        
class TestOnData(unittest.TestCase):
    def test_feeds_pyte_stream(self):
        s = make_session()
        s._on_data(b"hello")
        self.assertIn("hello", s.convert_screen_list_to_string())

    def test_subscriber_gets_called(self):
        s = make_session()
        received = []

        def cb(data):
            received.append(data)

        s.subscribe(cb)
        s._on_data(b"hello")
        self.assertEqual(received, [b"hello"])


class TestGetOutputSince(unittest.TestCase):
    def setUp(self):
        self.s = make_session()
        self.s._on_data(b"line1\r\nline2\r\nline3\r\n")

    def test_all_lines_visible_from_zero(self):
        out = self.s.get_output_since(0)
        for line in ("line1", "line2", "line3"):
            self.assertIn(line, out)

    def test_old_lines_hidden_after_cursor_advance(self):
        start = len(self.s.get_output_since(0).splitlines())
        self.s._on_data(b"line4\r\n")
        out = self.s.get_output_since(start)
        self.assertNotIn("line1", out)
        self.assertIn("line4", out)


class TestWaitUntilIdle(unittest.IsolatedAsyncioTestCase):
    async def test_settles_after_quiet_period(self):
        s = make_session()
        s._on_data(b"some output\r\n")
        result = await s.wait_until_idle(timeout_s=5, idle_s=0.3)
        self.assertTrue(result["done"])

    async def test_timeout_fires_when_screen_keeps_changing(self):
        s = make_session()

        async def keep_changing():
            for i in range(20):
                s._on_data(f"line{i}\r\n".encode())
                await asyncio.sleep(0.05)

        asyncio.create_task(keep_changing())
        result = await s.wait_until_idle(timeout_s=0.5, idle_s=5.0)
        self.assertFalse(result["done"])


class TestSessionFacadeEndSession(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._orig_session = session_facade.ssh_session
        self._orig_host = session_facade._host
        self._orig_username = session_facade._username

    def tearDown(self):
        session_facade.ssh_session = self._orig_session
        session_facade._host = self._orig_host
        session_facade._username = self._orig_username

    async def test_no_active_session(self):
        session_facade.ssh_session = None
        result = await session_facade.end_session()
        self.assertEqual(result, {"ok": False, "reason": "No active SSH session"})

    async def test_closes_and_clears_active_session(self):
        fake = MagicMock()
        fake.close = AsyncMock()
        fake.ssh_client = MagicMock()
        fake.ssh_client.on_disconnect = lambda: None
        session_facade.ssh_session = fake
        session_facade._host = "1.2.3.4"
        session_facade._username = "root"
        changed = asyncio.Event()
        session_facade.ssh_session_changed = changed

        result = await session_facade.end_session()

        self.assertEqual(result, {"ok": True})
        self.assertIsNone(session_facade.ssh_session)
        self.assertIsNone(session_facade._host)
        self.assertIsNone(session_facade._username)
        fake.close.assert_awaited_once()
        self.assertIsNone(fake.ssh_client.on_disconnect)
        self.assertTrue(changed.is_set())


class TestSessionFacadeOpenClosesPrevious(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._orig_session = session_facade.ssh_session
        self._orig_host = session_facade._host
        self._orig_username = session_facade._username

    def tearDown(self):
        session_facade.ssh_session = self._orig_session
        session_facade._host = self._orig_host
        session_facade._username = self._orig_username

    async def test_replaces_and_closes_previous_session(self):
        old = MagicMock()
        old.close = AsyncMock()
        old.ssh_client = MagicMock()
        old.ssh_client.on_disconnect = lambda: None
        session_facade.ssh_session = old
        session_facade._host = "old-host"
        session_facade._username = "old-user"

        new_instance = MagicMock()
        new_instance.start_ssh_client = AsyncMock()
        new_instance.ssh_client = MagicMock()

        with patch("session_facade.SSHSession", return_value=new_instance):
            result = await session_facade.open_ssh_session("new-host", "new-user", "pw")

        self.assertEqual(result, {"ok": True})
        old.close.assert_awaited_once()
        self.assertIsNone(old.ssh_client.on_disconnect)
        self.assertIs(session_facade.ssh_session, new_instance)
        self.assertEqual(session_facade._host, "new-host")


class TestHandleClientFrameEndSession(unittest.IsolatedAsyncioTestCase):
    async def test_end_session_message_closes_gracefully(self):
        fake_session = MagicMock()
        writer = MagicMock()
        writer.drain = AsyncMock()
        payload = b'{"type": "end_session"}'

        with patch.object(session_facade, "end_session", new=AsyncMock(return_value={"ok": True})) as mock_end:
            keep_going = await web_socket._handle_client_frame(fake_session, 0x1, payload, writer)

        self.assertFalse(keep_going)
        mock_end.assert_awaited_once()
        frame = writer.write.call_args[0][0]
        expected_payload = web_socket.NO_SESSION_CLOSE_CODE.to_bytes(2, "big") + b"no session"
        expected = bytearray([0x88, len(expected_payload)]) + expected_payload
        self.assertEqual(frame, expected)


class TestHandleClientFrameSessionRace(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._orig_session = session_facade.ssh_session

    def tearDown(self):
        session_facade.ssh_session = self._orig_session

    async def test_graceful_close_when_session_torn_down_mid_frame(self):
        fake_session = MagicMock()
        fake_session.write = AsyncMock(side_effect=ConnectionResetError("closed"))
        session_facade.ssh_session = None  # torn down by another connection mid-frame

        writer = MagicMock()
        writer.drain = AsyncMock()

        keep_going = await web_socket._handle_client_frame(fake_session, 0x2, b"ls\n", writer)

        self.assertFalse(keep_going)
        frame = writer.write.call_args[0][0]
        expected_payload = web_socket.NO_SESSION_CLOSE_CODE.to_bytes(2, "big") + b"no session"
        expected = bytearray([0x88, len(expected_payload)]) + expected_payload
        self.assertEqual(frame, expected)

    async def test_unrelated_errors_still_propagate(self):
        fake_session = MagicMock()
        fake_session.write = AsyncMock(side_effect=ValueError("bug"))
        session_facade.ssh_session = fake_session  # still the active session -- not a teardown race

        writer = MagicMock()
        writer.drain = AsyncMock()

        with self.assertRaises(ValueError):
            await web_socket._handle_client_frame(fake_session, 0x2, b"ls\n", writer)


class TestWriteAndReadResponseSessionEnded(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._orig_session = session_facade.ssh_session

    def tearDown(self):
        session_facade.ssh_session = self._orig_session

    async def test_detects_session_end_mid_wait(self):
        fake_session = MagicMock()
        fake_session.line_count.return_value = 0
        fake_session.write = AsyncMock()

        async def fake_wait_for_marker(marker, timeout_s):
            session_facade.ssh_session = None  # simulate end_session firing mid-wait
            return {"done": True}

        fake_session.wait_for_marker = fake_wait_for_marker
        session_facade.ssh_session = fake_session

        result = await mcp_server.write_and_read_response("ls")

        self.assertEqual(result, {"ok": False, "reason": "Session ended while waiting for output"})


class TestSessionFacadeOpenPreservesOnFailure(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._orig_session = session_facade.ssh_session
        self._orig_host = session_facade._host
        self._orig_username = session_facade._username

    def tearDown(self):
        session_facade.ssh_session = self._orig_session
        session_facade._host = self._orig_host
        session_facade._username = self._orig_username

    async def test_failed_reconnect_leaves_existing_session_untouched(self):
        good = MagicMock()
        good.close = AsyncMock()
        good.ssh_client = MagicMock()
        good.ssh_client.on_disconnect = lambda: None
        session_facade.ssh_session = good
        session_facade._host = "good-host"
        session_facade._username = "good-user"

        failing_instance = MagicMock()
        failing_instance.start_ssh_client = AsyncMock(side_effect=ConnectionError("bad credentials"))

        with patch("session_facade.SSHSession", return_value=failing_instance):
            result = await session_facade.open_ssh_session("bad-host", "bad-user", "wrong-pw")

        self.assertEqual(result, {"ok": False, "reason": "bad credentials"})
        self.assertIs(session_facade.ssh_session, good)
        self.assertEqual(session_facade._host, "good-host")
        good.close.assert_not_awaited()


class TestWriteAndReadResponsePersistentCursor(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._orig_session = session_facade.ssh_session

    def tearDown(self):
        session_facade.ssh_session = self._orig_session

    async def test_output_arriving_between_calls_is_not_lost(self):
        real_session = SSHSession("host", "user", "pass")
        real_session.ssh_client = MagicMock()

        async def fake_send_command(data):
            text = data.decode()
            real_session._on_data(data)

            async def deliver():
                await asyncio.sleep(0.05)  # lands after this call has already timed out and returned
                real_session._on_data(b"MARK-OUTPUT\r\n")
                marker = text.split("<<DONE:")[1].split(">>")[0]
                real_session._on_data(f"<<DONE:{marker}>>\r\n".encode())

            asyncio.create_task(deliver())

        real_session.ssh_client.send_command = AsyncMock(side_effect=fake_send_command)
        session_facade.ssh_session = real_session

        r1 = await mcp_server.write_and_read_response("echo MARK-OUTPUT", timeout=0.01)
        self.assertTrue(r1["timed_out"])

        # No tool call in flight while the output actually lands -- this is the gap that
        # used to be lost when output_start_line_index was captured fresh as "now" each call.
        await asyncio.sleep(0.15)

        r2 = await mcp_server.write_and_read_response("", timeout=0.05, is_command=False)
        self.assertIn("MARK-OUTPUT", r2["output"])


class TestWriteAndReadResponseCrossCallMarkerLeak(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._orig_session = session_facade.ssh_session

    def tearDown(self):
        session_facade.ssh_session = self._orig_session

    async def test_marker_completed_by_a_later_different_call_is_still_stripped(self):
        real_session = SSHSession("host", "user", "pass")
        real_session.ssh_client = MagicMock()

        async def fake_send_command(data):
            # Echo only -- the command never actually finishes during this call.
            real_session._on_data(data)

        real_session.ssh_client.send_command = AsyncMock(side_effect=fake_send_command)
        session_facade.ssh_session = real_session

        r1 = await mcp_server.write_and_read_response("sleep 5 && echo done-for-real", timeout=0.05)
        self.assertTrue(r1["timed_out"])
        marker = next(m for m in real_session.pending_markers)

        # The command finishes later, observed by a totally different, later call that
        # never generated a marker of its own (a plain is_command=False poll).
        real_session._on_data(b"done-for-real\r\n")
        real_session._on_data(f"{marker}\r\n".encode())
        real_session._on_data(b"user@host:~$ ")

        r2 = await mcp_server.write_and_read_response("", timeout=0.05, is_command=False)
        self.assertNotIn(marker, r2["output"])
        self.assertIn("done-for-real", r2["output"])


class TestWriteAndReadResponseMarkerStripping(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._orig_session = session_facade.ssh_session

    def tearDown(self):
        session_facade.ssh_session = self._orig_session

    async def test_strips_echoed_command_and_keeps_real_output(self):
        real_session = SSHSession("host", "user", "pass")
        real_session.ssh_client = MagicMock()

        async def fake_send_command(data):
            # A real PTY echoes back exactly what was sent -- including our injected marker
            # printf -- before the shell executes it and prints the real output, so the
            # marker text appears twice in what pyte renders.
            real_session._on_data(data)
            real_session._on_data(b"\r\n")
            real_session._on_data(b"total 4\r\n")
            real_session._on_data(b"drwxr-xr-x 2 user user 4096 file1\r\n")
            marker = data.decode().split("<<DONE:")[1].split(">>")[0]
            real_session._on_data(f"<<DONE:{marker}>>\r\n".encode())
            real_session._on_data(b"user@host:~$ ")

        real_session.ssh_client.send_command = AsyncMock(side_effect=fake_send_command)
        session_facade.ssh_session = real_session

        result = await mcp_server.write_and_read_response("ls -la")

        self.assertTrue(result["ok"])
        self.assertIn("total 4", result["output"])
        self.assertIn("drwxr-xr-x", result["output"])
        self.assertNotIn("printf", result["output"])
        self.assertNotIn("<<DONE:", result["output"])


class TestCleanOsErrorMessage(unittest.TestCase):
    def test_strips_winerror_prefix(self):
        e = OSError(121, "The semaphore timeout period has expired")
        e.winerror = 121
        e.strerror = "The semaphore timeout period has expired"
        self.assertEqual(_clean_os_error_message(e), "The semaphore timeout period has expired")

    def test_strips_errno_prefix(self):
        e = OSError(11001, "getaddrinfo failed")
        self.assertEqual(_clean_os_error_message(e), "getaddrinfo failed")

    def test_leaves_plain_message_unchanged(self):
        e = OSError("connection refused")
        self.assertEqual(_clean_os_error_message(e), "connection refused")


if __name__ == "__main__":
    unittest.main()
