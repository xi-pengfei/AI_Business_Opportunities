"""钉钉扫码登录与一次性邀请绑定：绑定、改绑、过期/已用/冒用等关键分支。"""
import pytest

from scout.config import settings


@pytest.fixture
def dingtalk_ready(monkeypatch):
    """配置钉钉凭证并 mock 掉真实换身份链路；open_id 可在用例里改写。"""
    monkeypatch.setenv("DINGTALK_APP_KEY", "test-key")
    monkeypatch.setenv("DINGTALK_APP_SECRET", "test-secret")
    monkeypatch.setenv("DINGTALK_REDIRECT_URI", "https://scout.example.com/dingtalk")
    settings.cache_clear()
    yield
    settings.cache_clear()


def mock_identity(monkeypatch, open_id="ding-open-1", union_id="ding-union-1"):
    from scout import dingtalk_sso

    monkeypatch.setattr(
        dingtalk_sso,
        "exchange_identity",
        lambda key, secret, code: {"open_id": open_id, "union_id": union_id, "nick": "席朋飞", "avatar_url": ""},
    )


def make_member(client):
    r = client.post(
        "/api/v1/users",
        json={"username": "席朋飞", "password": "1234.com", "display_name": "席朋飞"},
    )
    assert r.status_code == 201, r.text
    return r.json()


def restore_admin(client):
    """去掉临时会话后重新用管理员登录（invite/callback 场景需要游客身份）。"""
    client.headers.pop("Authorization", None)
    r = client.post(
        "/api/v1/auth/login",
        json={"username": settings().admin_username, "password": settings().admin_password},
    )
    assert r.status_code == 200, r.text
    client.headers["Authorization"] = f"Bearer {r.json()['access_token']}"


def test_dingtalk_config_hidden_without_credentials(client, database):
    r = client.get("/api/v1/auth/dingtalk/config")
    assert r.status_code == 200
    body = r.json()
    assert body["enabled"] is False


def test_dingtalk_config_exposes_redirect(client, database, dingtalk_ready):
    r = client.get("/api/v1/auth/dingtalk/config")
    body = r.json()
    assert body["enabled"] is True
    assert body["client_id"] == "test-key"
    assert body["redirect_uri"] == "https://scout.example.com/dingtalk"


def test_scan_without_binding_rejected(client, database, dingtalk_ready, monkeypatch):
    mock_identity(monkeypatch)
    r = client.post("/api/v1/auth/dingtalk/callback", json={"authCode": "code-1"})
    assert r.status_code == 403
    assert "邀请链接" in r.json()["detail"]


def test_invite_bind_then_scan_login(client, database, dingtalk_ready, monkeypatch):
    member = make_member(client)
    mock_identity(monkeypatch)

    link = client.post(f"/api/v1/users/{member['id']}/invite-link", json={})
    assert link.status_code == 201
    token = link.json()["token"]

    # 落地页信息
    info = client.get(f"/api/v1/auth/invite-info?token={token}")
    assert info.status_code == 200
    assert info.json()["display_name"] == "席朋飞"
    assert info.json()["used"] is False and info.json()["expired"] is False

    # 无鉴权（游客）也能完成绑定并直接拿到会话
    client.headers.pop("Authorization", None)
    bound = client.post(
        "/api/v1/auth/dingtalk/callback", json={"authCode": "code-1", "invite": token}
    )
    assert bound.status_code == 200, bound.text
    assert bound.json()["user"]["username"] == "席朋飞"

    # 绑定后：管理员列表显示已绑定；扫码登录（不带邀请）成功
    restore_admin(client)
    users = client.get("/api/v1/users").json()
    target = next(u for u in users if u["id"] == member["id"])
    assert target["identities"] == ["dingtalk"]
    client.headers.pop("Authorization", None)
    scan = client.post("/api/v1/auth/dingtalk/callback", json={"authCode": "code-2"})
    assert scan.status_code == 200
    assert scan.json()["user"]["id"] == member["id"]


def test_invite_single_use_and_regen_invalidates(client, database, dingtalk_ready, monkeypatch):
    member = make_member(client)
    mock_identity(monkeypatch)
    first = client.post(f"/api/v1/users/{member['id']}/invite-link", json={}).json()["token"]
    second = client.post(f"/api/v1/users/{member['id']}/invite-link", json={}).json()["token"]
    assert first != second

    # 重新生成后，旧链接立即过期
    client.headers.pop("Authorization")
    stale = client.post(
        "/api/v1/auth/dingtalk/callback", json={"authCode": "code-1", "invite": first}
    )
    assert stale.status_code == 409

    bound = client.post(
        "/api/v1/auth/dingtalk/callback", json={"authCode": "code-1", "invite": second}
    )
    assert bound.status_code == 200

    # 同一链接二次使用 → 已被使用
    again = client.post(
        "/api/v1/auth/dingtalk/callback", json={"authCode": "code-3", "invite": second}
    )
    assert again.status_code == 409
    assert "已被使用" in again.json()["detail"]


def test_dingtalk_account_cannot_bind_two_users(client, database, dingtalk_ready, monkeypatch):
    member_a = make_member(client)
    mock_identity(monkeypatch, open_id="dd-open-9", union_id="dd-union-9")
    client.post("/api/v1/users", json={"username": "zhangsan", "password": "zhang123456", "display_name": "张三"})
    users = client.get("/api/v1/users").json()
    member_b = next(u for u in users if u["username"] == "zhangsan")

    token_a = client.post(f"/api/v1/users/{member_a['id']}/invite-link", json={}).json()["token"]
    client.headers.pop("Authorization", None)
    assert client.post("/api/v1/auth/dingtalk/callback", json={"authCode": "c", "invite": token_a}).status_code == 200

    restore_admin(client)
    token_b = client.post(f"/api/v1/users/{member_b['id']}/invite-link", json={}).json()["token"]
    client.headers.pop("Authorization", None)
    stolen = client.post(
        "/api/v1/auth/dingtalk/callback", json={"authCode": "c2", "invite": token_b}
    )
    assert stolen.status_code == 409
    assert "已绑定其他用户" in stolen.json()["detail"]


def test_rebind_replaces_previous_identity(client, database, dingtalk_ready, monkeypatch):
    member = make_member(client)
    mock_identity(monkeypatch, open_id="dd-open-1", union_id="dd-union-1")
    token1 = client.post(f"/api/v1/users/{member['id']}/invite-link", json={}).json()["token"]
    client.headers.pop("Authorization")
    assert client.post("/api/v1/auth/dingtalk/callback", json={"authCode": "c1", "invite": token1}).status_code == 200

    # 换了钉钉账号（新 open_id）重新邀请 → 改绑成功且旧身份被替换
    mock_identity(monkeypatch, open_id="dd-open-2", union_id="dd-union-2")
    restore_admin(client)
    token2 = client.post(f"/api/v1/users/{member['id']}/invite-link", json={}).json()["token"]
    client.headers.pop("Authorization", None)
    rebind = client.post("/api/v1/auth/dingtalk/callback", json={"authCode": "c2", "invite": token2})
    assert rebind.status_code == 200
    scan = client.post("/api/v1/auth/dingtalk/callback", json={"authCode": "c3"})
    assert scan.status_code == 200 and scan.json()["user"]["id"] == member["id"]
