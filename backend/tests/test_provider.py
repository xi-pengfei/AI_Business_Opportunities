from types import SimpleNamespace

import httpx

from scout import providers


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
        lambda **kwargs: original(transport=httpx.MockTransport(handle), **kwargs),
    )
    results = providers.search(
        {"provider": "tavily", "query": "ERP", "max_results": 2},
        SimpleNamespace(tavily_api_key="test-key"),
    )
    assert results[0]["content_kind"] == "provider_body"
    assert results[0]["raw_content"] == "原始正文"
    assert results[1]["content_kind"] == "search_excerpt"
