"""Read-only adapter for the administrator-configured local xiaohongshu-mcp service."""

import json
import re
from datetime import datetime

import httpx

from scout.providers import ProviderError, SearchResults
from scout.quality import ZONE

ALLOWED = {
    ("GET", "/login/status"),
    ("GET", "/login/qrcode"),
    ("POST", "/feeds/search"),
    ("POST", "/feeds/detail"),
}
NOTE_ID = re.compile(r"^[0-9a-f]{24}$", re.I)


def request(config, method, path, body=None):
    if (method, path) not in ALLOWED:
        raise ProviderError("xhs_operation_not_allowed", True)
    if not config.xiaohongshu_url:
        raise ProviderError("xhs_not_configured", True)
    headers = (
        {"Authorization": f"Bearer {config.xiaohongshu_token}"} if config.xiaohongshu_token else {}
    )
    try:
        with httpx.Client(
            timeout=httpx.Timeout(40, connect=5), trust_env=False, follow_redirects=False
        ) as client:
            r = client.request(
                method,
                config.xiaohongshu_url.rstrip("/") + "/api/v1" + path,
                json=body,
                headers=headers,
            )
        data = r.json()
        if not isinstance(data, dict):
            raise ProviderError("xhs_invalid_response")
        if r.status_code >= 400 or data.get("success") is not True:
            detail = json.dumps(data, ensure_ascii=False).lower()
            if r.status_code == 429 or any(
                s in detail for s in ("captcha", "验证码", "风控", "访问频繁", "risk", "blocked")
            ):
                raise ProviderError("xhs_verification_required", True)
            if any(
                s in detail
                for s in ("未登录", "not logged", "login required", "登录失效", "登录已过期")
            ):
                raise ProviderError("xhs_login_required", True)
            if r.status_code in (401, 403):
                raise ProviderError("xhs_connector_authorization", True)
            raise ProviderError("xhs_request_failed")
        if not isinstance(data.get("data"), dict):
            raise ProviderError("xhs_invalid_response")
        return data["data"]
    except ProviderError:
        raise
    except (httpx.HTTPError, ValueError, TypeError):
        raise ProviderError("xhs_unavailable") from None


def login_status(config):
    data = request(config, "GET", "/login/status")
    if not isinstance(data.get("is_logged_in"), bool):
        raise ProviderError("xhs_invalid_response")
    return {"is_logged_in": data["is_logged_in"]}


def login_qrcode(config):
    data = request(config, "GET", "/login/qrcode")
    image = data.get("img", "")
    if not data.get("is_logged_in") and (
        not isinstance(image, str)
        or len(image) > 1000000
        or not re.fullmatch(r"data:image/(?:png|jpeg);base64,[A-Za-z0-9+/=\r\n]+", image)
    ):
        raise ProviderError("xhs_invalid_response")
    return {
        "is_logged_in": bool(data.get("is_logged_in")),
        "img": image,
        "timeout": str(data.get("timeout", ""))[:40],
    }


def search_notes(payload, config):
    if not login_status(config)["is_logged_in"]:
        raise ProviderError("xhs_login_required", True)
    data = request(
        config,
        "POST",
        "/feeds/search",
        {"keyword": payload["query"], "filters": {"sort_by": "最新", "publish_time": "半年内"}},
    )
    feeds = data.get("feeds")
    if not isinstance(feeds, list):
        raise ProviderError("xhs_invalid_response")
    results, seen = [], set()
    for feed in feeds:
        if not isinstance(feed, dict) or feed.get("modelType") != "note":
            continue
        note_id, token = feed.get("id", ""), feed.get("xsecToken", "")
        if not isinstance(note_id, str) or not NOTE_ID.fullmatch(note_id) or note_id in seen:
            continue
        if not isinstance(token, str) or not token or len(token) > 2000:
            raise ProviderError("xhs_invalid_response")
        seen.add(note_id)
        # note_token is a public-note navigation locator, never an account cookie.
        # It is removed after the detail has been read and is never returned to the UI.
        results.append(
            {
                "note_id": note_id,
                "note_token": token,
                "url": f"https://www.xiaohongshu.com/explore/{note_id}",
                "title": str((feed.get("noteCard") or {}).get("displayTitle") or "小红书笔记")[
                    :1000
                ],
                "raw_content": "",
                "content_kind": "pending_note",
                "published_at": None,
            }
        )
    return SearchResults(
        results,
        {"search_outcome": "results" if results else "empty", "search_engine": "xiaohongshu"},
    )


def read_note(payload, config):
    note_id = payload.get("note_id", "")
    if not NOTE_ID.fullmatch(note_id):
        raise ProviderError("invalid_source_url")
    data = request(
        config,
        "POST",
        "/feeds/detail",
        {"feed_id": note_id, "xsec_token": payload["note_token"], "load_all_comments": False},
    )
    note = (data.get("data") or {}).get("note")
    if not isinstance(note, dict) or note.get("noteId") != note_id:
        raise ProviderError("xhs_invalid_response")
    body = note.get("desc")
    if not isinstance(body, str) or not body.strip():
        raise ProviderError("empty_content")
    timestamp = note.get("time")
    date = None
    if isinstance(timestamp, (int, float)) and not isinstance(timestamp, bool) and timestamp > 0:
        try:
            date = (
                datetime.fromtimestamp(timestamp / 1000 if timestamp > 10**11 else timestamp, ZONE)
                .date()
                .isoformat()
            )
        except (ValueError, OverflowError, OSError):
            pass
    return {
        "title": str(note.get("title") or payload["title"])[:1000],
        "raw_content": body[:200000],
        "url": f"https://www.xiaohongshu.com/explore/{note_id}",
        "content_kind": "platform_note",
        "published_at": date,
    }
