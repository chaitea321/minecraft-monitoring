import discord
from discord import app_commands
from discord.ext import commands


class Help(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="help", description="List available commands")
    async def help(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="Minecraft Bot Commands",
            color=0x722F37,
        )
        embed.add_field(
            name="/status", value="Live TPS, players, heap, uptime", inline=False
        )
        embed.add_field(
            name="/players", value="List online players with play time", inline=False
        )
        embed.add_field(name="/tps", value="Current TPS value", inline=False)
        embed.add_field(name="/uptime", value="Server uptime", inline=False)
        embed.add_field(
            name="/whitelist add/remove <player>",
            value="Manage whitelist (admin only)",
            inline=False,
        )
        embed.add_field(
            name="/backup", value="Save world & trigger backup (admin only)", inline=False
        )
        embed.add_field(
            name="/ai-status",
            value="Check if AI model is running",
            inline=False,
        )
        embed.add_field(
            name="/analyze-lag",
            value="AI-powered server lag analysis",
            inline=False,
        )
        embed.add_field(
            name="/summarize",
            value="AI summary of recent server logs",
            inline=False,
        )
        embed.add_field(
            name="/help", value="Show this message", inline=False
        )
        await interaction.response.send_message(embed=embed)


async def setup(bot):
    await bot.add_cog(Help(bot))
