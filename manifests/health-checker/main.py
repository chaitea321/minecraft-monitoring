import asyncio
import json
import logging
import os
import sys
import time

import aiohttp

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("health-checker")

DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")
if not DISCORD_WEBHOOK_URL:
    sys.exit("FATAL: DISCORD_WEBHOOK_URL environment variable is required")

# Services to monitor — sub-path URLs behind Traefik ingress
SERVICES = [
    {"name": "Homepage", "url": "https://chai-homelab.com/homepage", "expected": 200},
    {"name": "Grafana", "url": "https://chai-homelab.com/grafana", "expected": 200},
    {"name": "Prometheus", "url": "https://chai-homelab.com/prometheus", "expected": 200},
    {"name": "Loki", "url": "https://chai-homelab.com/loki", "expected": 200},
    {"name": "ArgoCD", "url": "https://chai-homelab.com/argocd", "expected": 200},
]

# Dedup: track last alert time per service to avoid spam
LAST_ALERT = {}
DEDUP_WINDOW = 300  # 5 minutes


def severity_color(failing: int, total: int) -> int:
    ratio = failing / total if total > 0 else 1
    if ratio >= 0.8:
        return 0xE74C3C  # red
    elif ratio >= 0.4:
        return 0xF39C12  # orange
    return 0x3498DB  # blue


async def check_service(session: aiohttp.ClientSession, service: dict) -> dict:
    name = service["name"]
    url = service["url"]
    expected = service["expected"]

    try:
        async with session.get(
            url, timeout=aiohttp.ClientTimeout(total=15), allow_redirects=True
        ) as resp:
            status = resp.status
            elapsed = resp.headers.get("X-Response-Time", "?")
            return {
                "name": name,
                "url": url,
                "status": status,
                "expected": expected,
                "healthy": status == expected,
                "response_time": elapsed,
            }
    except asyncio.TimeoutError:
        return {
            "name": name,
            "url": url,
            "status": "timeout",
            "expected": expected,
            "healthy": False,
            "response_time": "N/A",
        }
    except Exception as e:
        return {
            "name": name,
            "url": url,
            "status": str(e),
            "expected": expected,
            "healthy": False,
            "response_time": "N/A",
        }


async def post_discord(embed: dict):
    async with aiohttp.ClientSession() as session:
        async with session.post(
            DISCORD_WEBHOOK_URL, json={"embeds": [embed]}, timeout=aiohttp.ClientTimeout(total=10)
        ) as resp:
            if resp.status >= 400:
                body = await resp.text()
                log.error("Discord webhook failed: %s %s", resp.status, body)


def build_health_embed(results: list, timestamp: str) -> dict:
    total = len(results)
    healthy = sum(1 for r in results if r["healthy"])
    failing = total - healthy

    fields = []
    for r in results:
        icon = "✅" if r["healthy"] else "❌"
        rt = f" ({r['response_time']}ms)" if r["response_time"] != "N/A" and r["response_time"] != "?" else ""
        fields.append(
            {
                "name": f"{icon} {r['name']}",
                "value": f"Status: {r['status']}{rt}",
                "inline": True,
            }
        )

    return {
        "title": f"🏥 Homelab Health Check — {healthy}/{total} services up",
        "description": f"Checked {total} services at {timestamp}" if healthy else f"⚠️ {failing} service(s) DOWN!",
        "color": severity_color(failing, total),
        "fields": fields,
        "footer": {"text": "chai-homelab health-checker"},
        "timestamp": timestamp,
    }


def build_alert_embed(results: list, timestamp: str) -> dict:
    failing = [r for r in results if not r["healthy"]]

    fields = []
    for r in failing:
        rt = f" ({r['response_time']}ms)" if r["response_time"] != "N/A" and r["response_time"] != "?" else ""
        fields.append(
            {
                "name": f"❌ {r['name']}",
                "value": f"URL: `{r['url']}`\nStatus: `{r['status']}`{rt}",
                "inline": False,
            }
        )

    return {
        "title": f"🚨 Homelab Service Alert — {len(failing)} service(s) DOWN!",
        "description": "One or more homelab services are unreachable.",
        "color": 0xE74C3C,
        "fields": fields,
        "footer": {"text": "chai-homelab health-checker"},
        "timestamp": timestamp,
    }


async def run_check():
    log.info("Running health check on %d services...", len(SERVICES))

    async with aiohttp.ClientSession() as session:
        tasks = [check_service(session, svc) for svc in SERVICES]
        results = await asyncio.gather(*tasks)

    timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    healthy = sum(1 for r in results if r["healthy"])
    total = len(results)

    # Post health summary embed every run
    health_embed = build_health_embed(results, timestamp)
    await post_discord(health_embed)
    log.info("Health summary posted: %d/%d up", healthy, total)

    # Alert on failures with dedup
    failing = [r for r in results if not r["healthy"]]
    if failing:
        now = time.time()
        should_alert = False
        for r in failing:
            last = LAST_ALERT.get(r["name"], 0)
            if now - last >= DEDUP_WINDOW:
                should_alert = True
                LAST_ALERT[r["name"]] = now

        if should_alert:
            alert_embed = build_alert_embed(failing, timestamp)
            await post_discord(alert_embed)
            log.warning("Alert sent for %d failing service(s)", len(failing))
    else:
        # Clear dedup on full health
        LAST_ALERT.clear()


def main():
    asyncio.run(run_check())


if __name__ == "__main__":
    main()
