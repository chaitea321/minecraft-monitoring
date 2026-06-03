import os

import discord
from discord import app_commands
from discord.ext import commands


def is_admin(interaction: discord.Interaction) -> bool:
    if interaction.user.guild_permissions.administrator:
        return True
    role_id = int(os.environ.get("ADMIN_ROLE_ID", "0"))
    if role_id and any(r.id == role_id for r in interaction.user.roles):
        return True
    return False


class Admin(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="whitelist", description="Add or remove a player from the whitelist")
    @app_commands.describe(action="add or remove", player="Minecraft username")
    @app_commands.choices(
        action=[
            app_commands.Choice(name="add", value="add"),
            app_commands.Choice(name="remove", value="remove"),
        ]
    )
    async def whitelist(
        self,
        interaction: discord.Interaction,
        action: str,
        player: str,
    ):
        if not is_admin(interaction):
            await interaction.response.send_message(
                "You need Administrator permission or the configured admin role to use this command.",
                ephemeral=True,
            )
            return

        await interaction.response.defer()
        try:
            result = await self.bot.rcon.command(f"whitelist {action} {player}")
            await interaction.followup.send(
                f"**/whitelist {action} {player}**\n```{result}```"
            )
        except Exception as e:
            await interaction.followup.send(f"RCON error: {e}")

    @app_commands.command(name="backup", description="Save the world and trigger a backup")
    async def backup(self, interaction: discord.Interaction):
        if not is_admin(interaction):
            await interaction.response.send_message(
                "You need Administrator permission or the configured admin role to use this command.",
                ephemeral=True,
            )
            return

        await interaction.response.defer()
        try:
            save_result = await self.bot.rcon.command("save-all")
            await interaction.followup.send(
                f"**Backup initiated**\nMinecraft save-all: OK\n```{save_result}```\nThe automated backup runs daily at 4 AM CST."
            )
        except Exception as e:
            await interaction.followup.send(f"Error: {e}")


async def setup(bot):
    await bot.add_cog(Admin(bot))
