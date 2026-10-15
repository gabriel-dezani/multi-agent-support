"""Bounded external search adapter; never turn provider outages into fake tickets."""
import httpx

from app.core.config import get_settings
from app.core.upstream import UpstreamUnavailable


class WebSearchTool:
    async def execute(self, query, max_results=5):
        settings = get_settings()
        if not settings.tavily_api_key:
            raise UpstreamUnavailable("Web search provider is not configured")
        payload = {
            "api_key": settings.tavily_api_key,
            "query": query,
            "max_results": max_results,
            "search_depth": "basic",
            "include_answer": False,
        }
        try:
            async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
                result = await client.post("https://api.tavily.com/search", json=payload)
                result.raise_for_status()
            response = result.json()
        except (httpx.HTTPError, ValueError) as exc:
            # Preserve neither raw upstream responses nor credentials in logs.
            raise UpstreamUnavailable("Web search provider unavailable") from exc
        if not isinstance(response, dict) or not isinstance(response.get("results"), list):
            raise UpstreamUnavailable("Web search provider returned an invalid response")
        return [
            {"title": item.get("title", ""), "url": item.get("url", ""),
             "content": item.get("content", "")}
            for item in response["results"] if isinstance(item, dict)
        ]
