"""钉钉扫码登录（OAuth2 授权码模式）。

链路（官方生产端点，不降级旧接口）：
1. 浏览器跳转 login.dingtalk.com/oauth2/auth，用户扫码同意后回调 /dingtalk?authCode=...&state=...；
2. POST /v1.0/oauth2/userAccessToken 用 authCode 换用户令牌；
3. GET /v1.0/contact/users/me（header: x-acs-dingtalk-access-token）拿 unionId / openId / 昵称。

身份只挂 user_identities（provider="dingtalk"），用户表不存渠道 ID。
"""

import logging
from urllib.parse import urlencode

import httpx

log = logging.getLogger(__name__)

AUTH_URL = "https://login.dingtalk.com/oauth2/auth"
TOKEN_URL = "https://api.dingtalk.com/v1.0/oauth2/userAccessToken"
ME_URL = "https://api.dingtalk.com/v1.0/contact/users/me"


class DingTalkError(RuntimeError):
    """钉钉登录链路失败，message 直接面向用户展示。"""


def authorize_url(client_id: str, redirect_uri: str, state: str, scope: str) -> str:
    """扫码授权页地址；桌面浏览器打开即显示二维码。"""
    query = urlencode(
        {
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "client_id": client_id,
            "scope": scope,
            "state": state,
            "prompt": "consent",
        }
    )
    return f"{AUTH_URL}?{query}"


def _fail(response: httpx.Response, step: str) -> DingTalkError:
    detail = ""
    try:
        body = response.json()
        # 新版接口错误结构：{code, message}；旧版：{errcode, errmsg}
        detail = body.get("message") or body.get("errmsg") or str(body)
    except Exception:
        detail = response.text[:200]
    return DingTalkError(f"钉钉{step}失败（HTTP {response.status_code}）：{detail}")


def exchange_identity(app_key: str, app_secret: str, auth_code: str) -> dict:
    """authCode → 用户身份 {open_id, union_id, nick, avatar_url}。

    用户令牌只在本函数内存中流转，不落库、不下发前端。
    """
    with httpx.Client(timeout=10) as client:
        token_resp = client.post(
            TOKEN_URL,
            json={
                "clientId": app_key,
                "clientSecret": app_secret,
                "code": auth_code,
                "grantType": "authorization_code",
            },
        )
        if token_resp.status_code != 200:
            raise _fail(token_resp, "授权码换取")
        access_token = token_resp.json().get("accessToken", "")
        if not access_token:
            raise DingTalkError("钉钉未返回用户令牌，请检查应用凭证配置")

        me_resp = client.get(
            ME_URL, headers={"x-acs-dingtalk-access-token": access_token}
        )
        if me_resp.status_code != 200:
            raise _fail(me_resp, "获取用户信息")
        info = me_resp.json()

    open_id = info.get("openId") or ""
    union_id = info.get("unionId") or open_id
    if not open_id and not union_id:
        raise DingTalkError("钉钉用户信息缺少 unionId/openId，无法绑定身份")
    result = {
        "open_id": open_id or union_id,
        "union_id": union_id,
        "nick": info.get("nick") or "",
        "avatar_url": info.get("avatarUrl") or "",
    }
    log.info("钉钉身份换取成功 unionId=%s nick=%s", union_id, result["nick"])
    return result
