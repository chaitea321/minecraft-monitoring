import asyncio

from mcrcon import MCRcon


class RCONClient:
    def __init__(self, host: str, port: int, password: str):
        self.host = host
        self.port = port
        self.password = password

    async def command(self, cmd: str) -> str:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            lambda: self._sync_command(cmd),
        )

    def _sync_command(self, cmd: str) -> str:
        with MCRcon(self.host, self.password, self.port) as rcon:
            return rcon.command(cmd)
