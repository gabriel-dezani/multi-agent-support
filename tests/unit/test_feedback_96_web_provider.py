"""Simulated remote search failures must become operational incidents, not handoffs."""
import asyncio
from types import SimpleNamespace

import httpx
import pytest

from app.core.upstream import UpstreamUnavailable
from app.tools import web_search


def test_missing_search_secret_is_not_a_customer_handoff(monkeypatch):
    monkeypatch.setattr(web_search, "get_settings", lambda: SimpleNamespace(tavily_api_key=""))
    with pytest.raises(UpstreamUnavailable, match="not configured"):
        asyncio.run(web_search.WebSearchTool().execute("test query"))


@pytest.mark.parametrize("status", [401, 429, 502, 503])
def test_http_provider_errors_are_classified_without_leaking_tokens(monkeypatch, status):
    secret = "a-private-test-secret"
    monkeypatch.setattr(web_search, "get_settings", lambda: SimpleNamespace(
        tavily_api_key=secret, request_timeout_seconds=5))

    class Client:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *_): return None
        async def post(self, url, json):
            assert json["api_key"] == secret
            return httpx.Response(status, request=httpx.Request("POST", url))

    monkeypatch.setattr(web_search.httpx, "AsyncClient", Client)
    with pytest.raises(UpstreamUnavailable) as info:
        asyncio.run(web_search.WebSearchTool().execute("weather"))
    assert secret not in str(info.value)


def test_malformed_provider_response_is_operational_failure(monkeypatch):
    monkeypatch.setattr(web_search, "get_settings", lambda: SimpleNamespace(
        tavily_api_key="test", request_timeout_seconds=5))

    class Client:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *_): return None
        async def post(self, url, json):
            return httpx.Response(200, json={"results": "not a list"}, request=httpx.Request("POST", url))

    monkeypatch.setattr(web_search.httpx, "AsyncClient", Client)
    with pytest.raises(UpstreamUnavailable):
        asyncio.run(web_search.WebSearchTool().execute("Getnet"))
