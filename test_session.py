import asyncio
import unittest
from unittest.mock import patch
from session import Session


def make_session():
    with patch("session.SSHClient"):
        s = Session("host", "user", "pass")
    return s


class TestOnData(unittest.TestCase):
    def test_feeds_pyte_stream(self):
        s = make_session()
        s._on_data(b"hello")
        self.assertIn("hello", s.convert_screen_list_to_string())

    def test_subscribers_get_called(self):
        pass  # covered async below


class TestOnDataAsync(unittest.IsolatedAsyncioTestCase):
    async def test_notifies_subscribers(self):
        s = make_session()
        received = []

        async def cb(data):
            received.append(data)

        s.subscribe(cb)
        s._on_data(b"hello")
        await asyncio.gather(*s.tasks)
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


if __name__ == "__main__":
    unittest.main()
