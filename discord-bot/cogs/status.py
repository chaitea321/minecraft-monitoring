import discord
from discord import app_commands
from discord.ext import commands


class Status(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="status", description="Live Minecraft server status")
    async def status(self, interaction: discord.Interaction):
        await interaction.response.defer()
        try:
            tps_data = await self.bot.prometheus.instant(
                "paper_tps_1m"
            )
            players_data = await self.bot.prometheus.instant(
                "increase(minecraft_play_time_ticks_total[5m]) > 0"
            )
            heap_data = await self.bot.prometheus.instant(
                "java_lang_Memory_HeapMemoryUsage_used / java_lang_Memory_HeapMemoryUsage_max"
            )
            uptime_data = await self.bot.prometheus.instant(
                'time() - process_start_time_seconds{job="minecraft-metrics"}'
            )

            tps = float(tps_data[0]["value"][1]) if tps_data else 0
            player_count = len(players_data)
            heap_pct = float(heap_data[0]["value"][1]) * 100 if heap_data else 0
            uptime_sec = float(uptime_data[0]["value"][1]) if uptime_data else 0
            days = int(uptime_sec // 86400)
            hours = int((uptime_sec % 86400) // 3600)

            embed = discord.Embed(
                title="Minecraft Server Status", color=0x722F37
            )
            embed.add_field(name="TPS", value=f"{tps:.1f}", inline=True)
            embed.add_field(
                name="Players Online", value=str(player_count), inline=True
            )
            embed.add_field(
                name="Heap", value=f"{heap_pct:.1f}%", inline=True
            )
            embed.add_field(
                name="Uptime", value=f"{days}d {hours}h", inline=True
            )
            await interaction.followup.send(embed=embed)
        except Exception as e:
            await interaction.followup.send(
                f"Error fetching server status: {e}"
            )

    @app_commands.command(name="players", description="List online players")
    async def players(self, interaction: discord.Interaction):
        await interaction.response.defer()
        try:
            data = await self.bot.prometheus.instant(
                "increase(minecraft_play_time_ticks_total[5m]) > 0"
            )
            if not data:
                embed = discord.Embed(
                    title="Online Players",
                    description="No players online",
                    color=0x722F37,
                )
                await interaction.followup.send(embed=embed)
                return

            lines = []
            for r in data:
                player = r["metric"].get("player", "unknown")
                ticks = float(r["value"][1])
                mins = ticks / 20 / 60
                lines.append(f"**{player}** — {mins:.0f} min played")

            embed = discord.Embed(
                title=f"Online Players ({len(lines)})",
                description="\n".join(lines),
                color=0x722F37,
            )
            await interaction.followup.send(embed=embed)
        except Exception as e:
            await interaction.followup.send(f"Error fetching players: {e}")

    @app_commands.command(name="tps", description="Current server TPS")
    async def tps(self, interaction: discord.Interaction):
        await interaction.response.defer()
        try:
            data = await self.bot.prometheus.instant(
                "paper_tps_1m"
            )
            tps = float(data[0]["value"][1]) if data else 0
            await interaction.followup.send(f"**Current TPS:** {tps:.1f}")
        except Exception as e:
            await interaction.followup.send(f"Error querying TPS: {e}")

    @app_commands.command(name="uptime", description="Server uptime")
    async def uptime(self, interaction: discord.Interaction):
        await interaction.response.defer()
        try:
            data = await self.bot.prometheus.instant(
                'time() - process_start_time_seconds{job="minecraft-metrics"}'
            )
            sec = float(data[0]["value"][1]) if data else 0
            days = int(sec // 86400)
            hours = int((sec % 86400) // 3600)
            await interaction.followup.send(
                f"**Server uptime:** {days}d {hours}h"
            )
        except Exception as e:
            await interaction.followup.send(f"Error querying uptime: {e}")

    @app_commands.command(name="session", description="Check player session duration")
    @app_commands.describe(player="Minecraft username")
    async def session(self, interaction: discord.Interaction, player: str):
        await interaction.response.defer()
        try:
            # Get total play time for this player
            data = await self.bot.prometheus.instant(
                f'minecraft_play_time_ticks_total{{player="{player}"}}'
            )
            if not data:
                await interaction.followup.send(f"Player **{player}** not found in metrics")
                return

            # Calculate session duration
            ticks = float(data[0]["value"][1])
            hours = int(ticks / 20 / 3600)
            minutes = int((ticks / 20 / 60) % 60)

            embed = discord.Embed(
                title=f"📊 Session: {player}",
                color=0x722F37
            )
            embed.add_field(name="Total Play Time", value=f"{hours}h {minutes}m", inline=True)
            await interaction.followup.send(embed=embed)
        except Exception as e:
            await interaction.followup.send(f"Error querying session: {e}")

    @app_commands.command(name="top-players", description="Show top 10 players by play time")
    async def top_players(self, interaction: discord.Interaction):
        await interaction.response.defer()
        try:
            data = await self.bot.prometheus.instant(
                'minecraft_play_time_ticks_total'
            )

            if not data:
                await interaction.followup.send("No player data found")
                return

            # Sort by play time
            sorted_data = sorted(data, key=lambda x: float(x["value"][1]), reverse=True)[:10]

            lines = []
            for i, r in enumerate(sorted_data, 1):
                player = r["metric"].get("player", "unknown")
                ticks = float(r["value"][1])
                hours = int(ticks / 20 / 3600)
                minutes = int((ticks / 20 / 60) % 60)
                lines.append(f"**{i}. {player}**: {hours}h {minutes}m")

            embed = discord.Embed(
                title=f"🏆 Top 10 Players by Play Time",
                description="\n".join(lines),
                color=0x722F37
            )
            await interaction.followup.send(embed=embed)
        except Exception as e:
            await interaction.followup.send(f"Error fetching top players: {e}")


async def setup(bot):
    await bot.add_cog(Status(bot))
