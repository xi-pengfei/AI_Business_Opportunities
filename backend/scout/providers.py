"""Only call the fixed search API. Never fetch result URLs in this milestone."""

import ipaddress
from urllib.parse import urlsplit, urlunsplit

import httpx
from bs4 import BeautifulSoup


class ProviderError(Exception):
    def __init__(self, code, action_required=False):
        self.code = code
        self.action_required = action_required


def canonical_url(value):
    try:
        parsed = urlsplit(value)
        host = parsed.hostname
        if parsed.scheme not in {"http", "https"} or not host or parsed.username or parsed.password:
            raise ValueError()
        if host.lower() == "localhost" or host.lower().endswith(
            (".localhost", ".local", ".internal")
        ):
            raise ValueError()
        try:
            if not ipaddress.ip_address(host).is_global:
                raise ValueError()
        except ValueError:
            # A hostname is allowed as evidence; this function NEVER authorizes a network fetch.
            if ":" in host or all(c.isdigit() or c == "." for c in host):
                raise
        port = parsed.port
        netloc = host.lower()
        if ":" in netloc:
            netloc = f"[{netloc}]"
        if port and (parsed.scheme, port) not in {("https", 443), ("http", 80)}:
            netloc += f":{port}"
        return urlunsplit((parsed.scheme, netloc, parsed.path or "/", parsed.query, ""))
    except (ValueError, TypeError):
        raise ProviderError("invalid_source_url") from None


def clean_text(raw):
    soup = BeautifulSoup(raw, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    return " ".join(soup.get_text(" ").split())


def search(payload, config):
    provider = payload["provider"]
    if provider == "demo":
        if not config.allow_demo:
            raise ProviderError("demo_disabled", True)
        return [
            {
                "title": f"演示：{payload['query']}",
                "url": "https://example.com/opportunities/supplier",
                "raw_content": "演示数据：希望把供应商对账和审批串起来，减少重复录入。",
                "content_kind": "demo",
                "published_at": None,
            }
        ]
    if provider != "tavily":
        raise ProviderError("provider_unavailable", True)
    if not config.tavily_api_key:
        raise ProviderError("search_key_missing", True)
    try:
        with httpx.Client(timeout=httpx.Timeout(45, connect=10), trust_env=False) as client:
            response = client.post(
                "https://api.tavily.com/search",
                headers={"Authorization": f"Bearer {config.tavily_api_key}"},
                json={
                    "query": payload["query"],
                    "max_results": payload["max_results"],
                    "search_depth": "basic",
                    "include_raw_content": "markdown",
                    "include_answer": False,
                    "auto_parameters": False,
                },
            )
        if response.status_code in (401, 403, 432, 433):
            raise ProviderError("search_authorization_required", True)
        if response.status_code == 429:
            raise ProviderError("search_rate_limited")
        response.raise_for_status()
        results = response.json()["results"]
        if not isinstance(results, list):
            raise ValueError()
        return [
            {
                "title": str(r.get("title") or "未命名来源")[:1000],
                "url": str(r.get("url") or ""),
                "raw_content": str(r.get("raw_content") or r.get("content") or "")[:200000],
                "content_kind": "provider_body" if r.get("raw_content") else "search_excerpt",
                "published_at": str(r["published_date"])[:100] if r.get("published_date") else None,
            }
            for r in results[: payload["max_results"]]
            if isinstance(r, dict)
        ]
    except ProviderError:
        raise
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        raise ProviderError("search_request_failed") from None
