import os
import sys

DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN")
if not DISCORD_TOKEN:
    sys.exit("FATAL: DISCORD_TOKEN environment variable is required")

PROMETHEUS_URL = os.environ.get(
    "PROMETHEUS_URL",
    "http://kube-prometheus-stack-prometheus.monitoring:9090/prometheus",
)
LOKI_URL = os.environ.get("LOKI_URL", "http://loki-gateway.monitoring:80")

RCON_HOST = os.environ.get("RCON_HOST", "minecraft-rcon.default")
RCON_PORT = int(os.environ.get("RCON_PORT", "25575"))
RCON_PASSWORD = os.environ.get("RCON_PASSWORD")
if not RCON_PASSWORD:
    sys.exit("FATAL: RCON_PASSWORD environment variable is required")

ADMIN_ROLE_ID = int(os.environ.get("ADMIN_ROLE_ID", "0"))

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://ollama.ollama:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "phi3")
