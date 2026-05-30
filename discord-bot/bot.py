import discord
from discord.ext import commands


class Bot(commands.Bot):
    def __init__(self, prometheus, rcon):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix=None, intents=intents)
        self.prometheus = prometheus
        self.rcon = rcon

    async def setup_hook(self):
        for ext in ["cogs.status", "cogs.admin", "cogs.help", "cogs.ai"]:
            await self.load_extension(ext)
        await self.tree.sync()

    async def on_ready(self):
        print(f"Logged in as {self.user} (ID: {self.user.id})")
