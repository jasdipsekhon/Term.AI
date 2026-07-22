import pyte
import asyncio
from ssh_client import SSHClient


class SSHSession:
    def __init__(self, host, username, password, cols=80, rows=24):
        self.host = host
        self.username = username
        self.password = password
        self.cols = cols
        self.rows = rows
        self.ssh_client = None
        self.screen = pyte.HistoryScreen(cols, rows, history=10000)  # deque of lines; each line is a dict of column_index -> Char
        self.stream = pyte.Stream(self.screen)  # parses raw bytes and updates screen
        self.subscriber = None  # (callback, ctx) for the connected browser viewer
        self.tasks = set()      # asyncio tasks for subscriber callbacks

    def _on_data(self, data):
        bytes_to_str = data.decode("utf-8", errors="replace")
        self.stream.feed(bytes_to_str)
        self._notify_subscriber(data)

    async def start_ssh_client(self):
        self.ssh_client = SSHClient(self.host, self.username, self.password, self._on_data)
        await self.ssh_client.connect()

    async def resize(self, width, height):
        self.cols = width
        self.rows = height
        self.screen.resize(height, width)
        if self.ssh_client:
            await self.ssh_client.resize(width, height)

    async def write(self, data):
        if self.ssh_client:
            await self.ssh_client.send_command(data)

    async def close(self):
        for task in list(self.tasks):
                task.cancel()
        if self.ssh_client:
            await self.ssh_client.close()

    # ── Pyte interface ──────────────────────────────────────────────────

    def line_count(self):
        return len(self.screen.history.top) + self.screen.cursor.y

    def convert_screen_list_to_string(self):
        return "\n".join(self.screen.display)
    
    async def wait_until_idle(self, timeout_s=30, idle_s=0.3):
        idle = False
        current_event_loop = asyncio.get_running_loop()
        start_time = current_event_loop.time()
        time_of_change = start_time
        last_string = self.convert_screen_list_to_string()
        while current_event_loop.time() - start_time < timeout_s:
            await asyncio.sleep(0.05)
            current_string = self.convert_screen_list_to_string()
            if current_string != last_string:
                last_string = current_string
                time_of_change = current_event_loop.time()
            if current_event_loop.time() - time_of_change >= idle_s:
                idle = True
                return {"done": idle}
        return {"done": idle, "reason": "Timeout reached before idle state."}
    
    def get_output_since(self, start_line):
        history = []
        for line_key in self.screen.history.top:
            row = ""
            for col in range(self.cols):
                if col in line_key:
                    row += line_key[col].data
                else:
                    row += " "
            row = row.rstrip()
            history.append(row)
        visible = []
        for row in self.screen.display:
            row = row.rstrip()
            visible.append(row)
        whole_screen = history + visible
        lines_after_start = whole_screen[start_line:]
        while lines_after_start and not lines_after_start[-1]:
            lines_after_start.pop()
        return "\n".join(lines_after_start)


    # ── WebSocket interface ──────────────────────────────────────────────────

    def subscribe(self, subscriber, ctx=None):
        self.subscriber = (subscriber, ctx)

    def unsubscribe(self, subscriber):
        self.subscriber = None

    def _notify_subscriber(self, data):
        if self.subscriber is None:
            return
        callback, ctx = self.subscriber
        task = asyncio.create_task(callback(data, ctx))
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
