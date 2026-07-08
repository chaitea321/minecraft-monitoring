import aiohttp


class PrometheusClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    async def instant(self, query: str):
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{self.base_url}/api/v1/query",
                params={"query": query},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                data = await resp.json()
                if data["status"] != "success":
                    raise Exception(f"Prometheus query failed: {data}")
                return data["data"]["result"]
