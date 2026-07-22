import asyncssh

class SSHSessionHandler(asyncssh.SSHClientSession):
    def __init__(self, client):
        self.client = client

    def data_received(self, data, _):
        self.client.on_data(data)

    def connection_lost(self, _):
        # Read on_disconnect lazily — it is assigned after connect() returns.
        if self.client.on_disconnect:
            self.client.on_disconnect()


class SSHClient:
    def __init__(self, host, username, password, on_data):
        self.host = host
        self.username = username
        self.password = password
        self.connection = None
        self.channel = None
        self.on_data = on_data
        self.on_disconnect = None

    async def connect(self):
        self.connection = await asyncssh.connect(self.host, username=self.username, password=self.password, known_hosts=None)
        self.channel, _ = await self.connection.create_session(lambda: SSHSessionHandler(self), request_pty=True, term_type='xterm-256color', encoding=None)

    async def send_command(self, command):
        if self.channel is None:
            raise ConnectionError("SSH session is not established.")
        self.channel.write(command)

    async def resize(self, width, height):
        if self.channel is None:
            raise ConnectionError("SSH session is not established.")
        self.channel.change_terminal_size(width, height)

    async def close(self):
        if self.channel is not None:
            self.channel.close()
            self.channel = None
        if self.connection is not None:
            self.connection.close()
            await self.connection.wait_closed()
            self.connection = None
