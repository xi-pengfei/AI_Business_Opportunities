from types import SimpleNamespace

import httpx
import pytest

from scout import providers


def provider_transport(handle):
    def route(request):
        if request.url.path == "/config":
            return httpx.Response(200,json={"engines":[{"name":name,"enabled":True} for name in ("bing","duckduckgo")]})
        return handle(request)
    return httpx.MockTransport(route)


def test_search_preserves_body_and_labels_excerpt(monkeypatch):
    original = httpx.Client

    def handle(request):
        assert request.url == "https://api.tavily.com/search"
        assert request.headers["Authorization"] == "Bearer test-key"
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "title": "正文",
                        "url": "https://example.com/a",
                        "raw_content": "原始正文",
                        "content": "摘要",
                    },
                    {
                        "title": "摘要",
                        "url": "https://example.com/b",
                        "raw_content": None,
                        "content": "只有摘要",
                    },
                ]
            },
        )

    monkeypatch.setattr(
        providers.httpx,
        "Client",
        lambda **kwargs: original(transport=provider_transport(handle), **kwargs),
    )
    results = providers.search(
        {"provider": "tavily", "query": "ERP", "max_results": 2},
        SimpleNamespace(tavily_api_key="test-key"),
    )
    assert results[0]["content_kind"] == "provider_body"
    assert results[0]["raw_content"] == "原始正文"
    assert results[1]["content_kind"] == "search_excerpt"


def test_searxng_returns_all_results_as_excerpts_without_paid_fallback(monkeypatch):
    original = httpx.Client

    def handle(request):
        assert request.url.host == "searxng"
        assert request.url.params["pageno"] == "2"
        assert "Authorization" not in request.headers
        return httpx.Response(
            200,
            json={
                "results": [
                    {"title": str(i), "url": f"https://example.org/{i}", "content": "搜索摘要"}
                    for i in range(25)
                ]
            },
        )

    monkeypatch.setattr(
        providers.httpx,
        "Client",
        lambda **kwargs: original(transport=provider_transport(handle), **kwargs),
    )
    result = providers.search(
        {"provider": "searxng", "query": "ERP", "page": 2, "max_results": 20},
        SimpleNamespace(searxng_url="http://searxng:8080"),
    )
    assert len(result) == 25
    assert all(r["content_kind"] == "search_excerpt" for r in result)


def test_searxng_engine_failure_is_retryable_and_never_calls_paid_provider(monkeypatch):
    original = httpx.Client
    calls = []

    def handle(request):
        calls.append(request.url.host)
        return httpx.Response(
            200, json={"results": [], "unresponsive_engines": [["bing", "timeout"], ["duckduckgo", "timeout"]]}
        )

    monkeypatch.setattr(
        providers.httpx,
        "Client",
        lambda **kwargs: original(transport=provider_transport(handle), **kwargs),
    )
    with pytest.raises(providers.ProviderError) as error:
        providers.search(
            {"provider": "searxng", "query": "ERP"},
            SimpleNamespace(searxng_url="http://searxng:8080", tavily_api_key="unused"),
        )
    assert error.value.code == "searxng_engines_unavailable"
    assert not error.value.action_required
    assert calls == ["searxng"]


def test_partial_failure_with_no_results_is_not_claimed_as_true_empty(monkeypatch):
    original = httpx.Client
    monkeypatch.setattr(providers.httpx, "Client", lambda **kwargs: original(
        transport=provider_transport(lambda request: httpx.Response(
            200, json={"results": [], "unresponsive_engines": [["duckduckgo", "timeout"]]}
        )), **kwargs))
    with pytest.raises(providers.ProviderError, match="searxng_engines_unavailable"):
        providers.search({"provider": "searxng", "query": "rare phrase"},
                         SimpleNamespace(searxng_url="http://searxng:8080"))


@pytest.mark.parametrize('status, failures',[(429,[]),(200, [['duckduckgo','CAPTCHA']])])
def test_rate_limit_is_not_a_normal_empty_result(monkeypatch,status,failures):
    original=httpx.Client
    monkeypatch.setattr(providers.httpx,'Client',lambda **kwargs: original(
        transport=provider_transport(lambda request: httpx.Response(status,json={'results':[],'unresponsive_engines':failures})),**kwargs))
    with pytest.raises(providers.ProviderError,match='searxng_rate_limited'):
        providers.search({'provider':'searxng','query':'ERP','engine':'duckduckgo'},SimpleNamespace(searxng_url='http://searxng:8080'))


def test_disabled_engine_is_never_counted_as_successful_search(monkeypatch):
    original=httpx.Client
    calls=[]
    def response(request):
        calls.append(request.url.path)
        return httpx.Response(200,json={'engines':[{'name':'bing','enabled':False}]})
    monkeypatch.setattr(providers.httpx,'Client',lambda **kwargs: original(transport=httpx.MockTransport(response),**kwargs))
    with pytest.raises(providers.ProviderError,match='searxng_engines_disabled'):
        providers.search({'provider':'searxng','query':'ERP','engine':'bing'},SimpleNamespace(searxng_url='http://searxng:8080'))
    assert calls==['/config']
