"""Only call fixed or administrator-configured search services. Never fetch result URLs in this milestone."""

import ipaddress
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

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
        return urlunsplit((parsed.scheme, netloc, parsed.path or "/", urlencode(sorted((k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True) if not k.lower().startswith("utm_") and k.lower() not in {"gclid", "fbclid", "msclkid"})), ""))
    except (ValueError, TypeError):
        raise ProviderError("invalid_source_url") from None


def clean_text(raw):
    soup = BeautifulSoup(raw, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    return " ".join(soup.get_text(" ").split())


def search(payload, config):
    provider = payload["provider"]
    if provider == "searxng":
        return search_searxng(payload, config)
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


def search_searxng(payload, config):
    """Administrator-configured service; result URLs are evidence, never fetched here."""
    if not config.searxng_url:
        raise ProviderError("searxng_not_configured", True)
    engines = {e.strip() for e in getattr(config, "searxng_engines", "bing,duckduckgo").split(",") if e.strip()}
    if not engines:
        raise ProviderError("searxng_not_configured", True)
    try:
        with httpx.Client(timeout=httpx.Timeout(25, connect=5), trust_env=False) as client:
            response = client.get(
                config.searxng_url.rstrip("/") + "/search",
                params={
                    "q": payload["query"],
                    "format": "json",
                    "language": "zh-CN",
                    "categories": "general",
                    "engines": ",".join(sorted(engines)),
                    "pageno": payload.get("page", 1),
                    "time_range": "month",
                },
            )
        response.raise_for_status()
        data = response.json()
        results = data.get("results")
        if not isinstance(results, list):
            raise ValueError()
        failed = {row[0] for row in data.get("unresponsive_engines", []) if isinstance(row, list) and row}
        if not results and engines.issubset(failed):
            raise ProviderError("searxng_engines_unavailable")
        return [
            {
                "title": str(r.get("title") or "未命名来源")[:1000],
                "url": str(r.get("url") or ""),
                "raw_content": str(r.get("content") or r.get("title") or "")[:200000],
                "content_kind": "search_excerpt",
                "published_at": str(r.get("publishedDate") or r.get("published_date") or "") or None,
            }
            for r in results
            if isinstance(r, dict) and r.get("url")
        ]
    except ProviderError:
        raise
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        raise ProviderError("searxng_request_failed") from None
