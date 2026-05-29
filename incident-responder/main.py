import asyncio
import json
import logging
import os
import time

import aiohttp
from aiohttp import web

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("incident-responder")

DISCORD_WEBHOOK_URL = os.environ["DISCORD_WEBHOOK_URL"]
PROMETHEUS_URL = os.environ.get(
    "PROMETHEUS_URL",
    "http://kube-prometheus-stack-prometheus.monitoring:9090/prometheus",
)
LOKI_URL = os.environ.get(
    "LOKI_URL",
    "http://loki-gateway.monitoring:80",
)
OLLAMA_URL = os.environ.get("OLLAMA_URL", "")  # empty = skip AI
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "phi3")

# Track alert fingerprints to avoid duplicate diagnostics
RECENT_ALERTS = {}
DEDUP_WINDOW = 300  # seconds


def is_duplicate(fingerprint: str) -> bool:
    now = time.time()
    if fingerprint in RECENT_ALERTS:
        if now - RECENT_ALERTS[fingerprint] < DEDUP_WINDOW:
            return True
    RECENT_ALERTS[fingerprint] = now
    return False


def severity_color(severity: str) -> int:
    return {"critical": 0xE74C3C, "warning": 0xF39C12, "info": 0x3498DB}.get(
        severity, 0x95A5A6
    )


async def post_discord(embed: dict):
    async with aiohttp.ClientSession() as session:
        async with session.post(DISCORD_WEBHOOK_URL, json={"embeds": [embed]}) as resp:
            if resp.status >= 400:
                body = await resp.text()
                log.error("Discord webhook failed: %s %s", resp.status, body)


async def query_prometheus(query: str) -> list | None:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{PROMETHEUS_URL}/api/v1/query",
                params={"query": query},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                data = await resp.json()
                if data["status"] == "success":
                    return data["data"]["result"]
    except Exception as e:
        log.warning("Prometheus query failed: %s — %s", query, e)
    return None


async def query_loki(query: str, minutes: int = 5) -> str:
    try:
        params = {
            "query": query,
            "start": str(int((time.time() - minutes * 60) * 1e9)),
            "end": str(int(time.time() * 1e9)),
            "limit": "50",
        }
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{LOKI_URL}/loki/api/v1/query_range",
                params=params,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                data = await resp.json()
                if data["status"] == "success":
                    lines = []
                    for result in data["data"]["result"]:
                        for ts, line in result.get("values", []):
                            lines.append(line)
                    return "\n".join(lines[-30:])
    except Exception as e:
        log.warning("Loki query failed: %s", e)
    return ""


async def query_ollama(prompt: str, timeout: int = 30) -> str | None:
    if not OLLAMA_URL:
        return None
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{OLLAMA_URL}/api/generate",
                json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False},
                timeout=aiohttp.ClientTimeout(total=timeout),
            ) as resp:
                if resp.status != 200:
                    log.warning("Ollama returned %s", resp.status)
                    return None
                data = await resp.json()
                return data.get("response", "").strip()
    except Exception as e:
        log.warning("Ollama query failed: %s", e)
    return None


async def gather_diagnostics() -> dict:
    tps_data = await query_prometheus(
        "minecraft_tps_bucket_sum / minecraft_tps_bucket_count"
    )
    heap_data = await query_prometheus(
        "java_lang_Memory_HeapMemoryUsage_used / java_lang_Memory_HeapMemoryUsage_max"
    )
    load_data = await query_prometheus(
        "java_lang_OperatingSystem_SystemLoadAverage"
    )
    players_data = await query_prometheus(
        "increase(minecraft_play_time_ticks_total[5m]) > 0"
    )
    uptime_data = await query_prometheus(
        'time() - process_start_time_seconds{job="minecraft-metrics"}'
    )
    logs = await query_loki('{app="minecraft"}', 5)

    tps = float(tps_data[0]["value"][1]) if tps_data else None
    heap = float(heap_data[0]["value"][1]) if heap_data else None
    load = float(load_data[0]["value"][1]) if load_data else None
    players = len(players_data) if players_data else 0
    uptime_sec = float(uptime_data[0]["value"][1]) if uptime_data else None

    return {
        "tps": tps,
        "heap_pct": heap * 100 if heap is not None else None,
        "load": load,
        "players": players,
        "uptime_days": round(uptime_sec / 86400, 1) if uptime_sec else None,
        "logs_sample": logs[:1000] if logs else "",
    }


def build_alert_embed(alert: dict) -> dict:
    labels = alert.get("labels", {})
    annotations = alert.get("annotations", {})
    severity = labels.get("severity", "info")
    name = labels.get("alertname", "Unknown")
    status = alert.get("status", "firing")

    desc = annotations.get("description", annotations.get("summary", ""))
    color = severity_color(severity)

    embed = {
        "title": f"{'🔥' if status == 'firing' else '✅'} {name}",
        "description": desc,
        "color": color,
        "fields": [],
        "timestamp": alert.get("startsAt", ""),
    }

    for k, v in sorted(labels.items()):
        if k not in ("alertname", "severity", "namespace"):
            embed["fields"].append({"name": k, "value": v, "inline": True})

    values = alert.get("values", {})
    if values:
        embed["fields"].append(
            {"name": "Value", "value": str(values.get("A", "?")), "inline": True}
        )

    return embed


def build_diagnostic_embed(alert: dict, diag: dict) -> dict:
    labels = alert.get("labels", {})
    name = labels.get("alertname", "Unknown")
    severity = labels.get("severity", "info")

    fields = []
    if diag["tps"] is not None:
        fields.append({"name": "TPS", "value": f"{diag['tps']:.1f}", "inline": True})
    if diag["heap_pct"] is not None:
        fields.append(
            {"name": "Heap", "value": f"{diag['heap_pct']:.1f}%", "inline": True}
        )
    if diag["load"] is not None:
        fields.append(
            {"name": "System Load", "value": f"{diag['load']:.2f}", "inline": True}
        )
    fields.append({"name": "Players", "value": str(diag["players"]), "inline": True})
    if diag["uptime_days"] is not None:
        fields.append(
            {"name": "Uptime", "value": f"{diag['uptime_days']}d", "inline": True}
        )

    description = f"Diagnostics for **{name}**"
    if diag["logs_sample"]:
        # Truncate and escape for Discord
        log_sample = diag["logs_sample"][:500].replace("`", "'")
        fields.append(
            {
                "name": "Recent Logs (last 5m)",
                "value": f"```{log_sample}```",
                "inline": False,
            }
        )

    return {
        "title": f"📊 {name} — Diagnostics",
        "description": description,
        "color": severity_color(severity),
        "fields": fields,
        "timestamp": alert.get("startsAt", ""),
    }


def build_ai_embed(alert: dict, analysis: str) -> dict:
    labels = alert.get("labels", {})
    name = labels.get("alertname", "Unknown")
    severity = labels.get("severity", "info")
    return {
        "title": f"🤖 {name} — AI Analysis",
        "description": analysis[:2000],
        "color": severity_color(severity),
        "footer": {"text": f"Model: {OLLAMA_MODEL}"},
    }


async def handle_webhook(request: web.Request) -> web.Response:
    try:
        payload = await request.json()
    except Exception as e:
        log.error("Failed to parse webhook payload: %s", e)
        return web.Response(status=400, text="invalid json")

    alerts = payload.get("alerts", [])
    log.info("Received %d alert(s)", len(alerts))

    async def process_alerts():
        for alert in alerts:
            fingerprint = alert.get("fingerprint", "")
            if is_duplicate(fingerprint):
                log.info("Skipping duplicate alert: %s", fingerprint)
                continue

            status = alert.get("status", "firing")
            labels = alert.get("labels", {})
            name = labels.get("alertname", "Unknown")
            log.info("Processing alert: %s (%s)", name, status)

            # 1. Forward alert embed to Discord
            alert_embed = build_alert_embed(alert)
            await post_discord(alert_embed)

            # 2. Gather diagnostics
            diag = await gather_diagnostics()

            # 3. Post diagnostic embed
            diag_embed = build_diagnostic_embed(alert, diag)
            await post_discord(diag_embed)

            # 4. AI analysis via Ollama (best-effort, never blocks)
            try:
                prompt = (
                    f"Analyze this Minecraft server alert.\n"
                    f"Alert: {name} ({labels.get('severity', '?')})\n"
                    f"TPS: {diag['tps']}, Heap: {diag['heap_pct']}%, "
                    f"Load: {diag['load']}, Players: {diag['players']}\n"
                    f"Recent logs:\n{diag['logs_sample'][:800]}\n\n"
                    f"What is likely causing this issue and what should "
                    f"the admin do? Be concise (3-5 sentences)."
                )
                analysis = await query_ollama(prompt)
                if analysis:
                    ai_embed = build_ai_embed(alert, analysis)
                    await post_discord(ai_embed)
            except Exception as e:
                log.warning("AI analysis failed (non-critical): %s", e)

            log.info("Completed diagnostics for: %s", name)

    asyncio.ensure_future(process_alerts())
    return web.Response(status=200, text="ok")


async def health(request: web.Request) -> web.Response:
    return web.Response(status=200, text="ok")


def main():
    app = web.Application()
    app.router.add_post("/webhook", handle_webhook)
    app.router.add_get("/health", health)

    port = int(os.environ.get("PORT", "8080"))
    log.info("Starting incident-responder on port %d", port)
    web.run_app(app, host="0.0.0.0", port=port, access_log=None)


if __name__ == "__main__":
    main()
