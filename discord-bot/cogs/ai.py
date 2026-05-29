import os
import textwrap

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

OLLAMA_URL = os.environ.get(
    "OLLAMA_URL", "http://ollama.ollama:11434"
)
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "phi3")


async def query_ollama(prompt: str, timeout: int = 60) -> str:
    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"{OLLAMA_URL}/api/generate",
            json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False},
            timeout=aiohttp.ClientTimeout(total=timeout),
        ) as resp:
            if resp.status != 200:
                body = await resp.text()
                raise Exception(f"Ollama returned {resp.status}: {body}")
            data = await resp.json()
            return data.get("response", "").strip()


async def check_ollama_health() -> str:
    async with aiohttp.ClientSession() as session:
        async with session.get(
            f"{OLLAMA_URL}/api/tags",
            timeout=aiohttp.ClientTimeout(total=5),
        ) as resp:
            if resp.status != 200:
                return "unreachable"
            data = await resp.json()
            models = data.get("models", [])
            if not models:
                return "no models loaded"
            names = [m["name"] for m in models]
            return f"online — models: {', '.join(names)}"


class AI(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(
        name="ai-status", description="Check if the AI model (Ollama) is running"
    )
    async def ai_status(self, interaction: discord.Interaction):
        await interaction.response.defer()
        try:
            status = await check_ollama_health()
            await interaction.followup.send(f"**Ollama:** {status}")
        except Exception as e:
            await interaction.followup.send(f"**Ollama:** error — {e}")

    @app_commands.command(
        name="analyze-lag",
        description="Analyze server lag causes using AI",
    )
    async def analyze_lag(self, interaction: discord.Interaction):
        await interaction.response.defer()
        try:
            tps_data = await self.bot.prometheus.instant(
                "minecraft_tps_bucket_sum / minecraft_tps_bucket_count"
            )
            heap_data = await self.bot.prometheus.instant(
                "java_lang_Memory_HeapMemoryUsage_used / java_lang_Memory_HeapMemoryUsage_max"
            )
            load_data = await self.bot.prometheus.instant(
                "java_lang_OperatingSystem_SystemLoadAverage"
            )
            players_data = await self.bot.prometheus.instant(
                "increase(minecraft_play_time_ticks_total[5m]) > 0"
            )

            tps = float(tps_data[0]["value"][1]) if tps_data else "N/A"
            heap = (
                f"{float(heap_data[0]['value'][1]) * 100:.1f}%"
                if heap_data
                else "N/A"
            )
            load = float(load_data[0]["value"][1]) if load_data else "N/A"
            players = len(players_data) if players_data else 0

            prompt = textwrap.dedent(f"""\
                You are a Minecraft server admin assistant. Analyze this situation:
                - TPS (ticks per second): {tps} (target: 20.0)
                - JVM heap usage: {heap}
                - System load average: {load}
                - Players online: {players}

                What is likely causing performance issues? Be concise (3-5 sentences).
                Suggest specific things the admin should check.""")
            analysis = await query_ollama(prompt)

            embed = discord.Embed(
                title="🤖 Lag Analysis",
                description=analysis,
                color=0x722F37,
            )
            embed.add_field(
                name="TPS", value=str(tps), inline=True
            )
            embed.add_field(
                name="Heap", value=str(heap), inline=True
            )
            embed.add_field(
                name="Load", value=str(load), inline=True
            )
            embed.add_field(
                name="Players", value=str(players), inline=True
            )
            await interaction.followup.send(embed=embed)
        except Exception as e:
            await interaction.followup.send(
                f"Error during lag analysis: {e}"
            )

    @app_commands.command(
        name="summarize",
        description="Summarize recent server activity from logs",
    )
    async def summarize(self, interaction: discord.Interaction):
        await interaction.response.defer()
        try:
            async with aiohttp.ClientSession() as session:
                params = {
                    "query": '{app="minecraft"}',
                    "limit": "100",
                }
                async with session.get(
                    f"http://loki-gateway.monitoring:80/loki/api/v1/query_range",
                    params=params,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    data = await resp.json()

            lines = []
            if data.get("status") == "success":
                for result in data["data"]["result"]:
                    for ts, line in result.get("values", []):
                        lines.append(line)

            if not lines:
                await interaction.followup.send(
                    "No recent logs found to summarize."
                )
                return

            log_text = "\n".join(lines[-50:])
            log_text = log_text[:1500]

            prompt = textwrap.dedent(f"""\
                Summarize the following Minecraft server log entries from the
                last few minutes. Focus on player activity, warnings, and errors.
                Be concise (3-5 sentences).

                Logs:
                {log_text}""")
            summary = await query_ollama(prompt)

            embed = discord.Embed(
                title="📋 Recent Activity Summary",
                description=summary,
                color=0x722F37,
            )
            embed.set_footer(text=f"Based on {len(lines)} log entries")
            await interaction.followup.send(embed=embed)
        except Exception as e:
            await interaction.followup.send(
                f"Error during summarization: {e}"
            )


async def setup(bot):
    await bot.add_cog(AI(bot))
