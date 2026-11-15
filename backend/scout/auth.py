"""本机账号体系：argon2 口令 + JWT 会话 + 个人 API 密钥。

设计约定（与产品方案一致）：
- ADMIN_TOKEN 彻底下线，运维就是 role=admin 的系统管理员，走同一个登录入口；
- 展示令牌（大屏）保留，屏幕场景没有键盘，令牌不可替代；
- 用户表不存任何渠道 ID，钉钉/飞书/企微一律挂 user_identities，三家同权重。
"""

import hashlib
import logging
import secrets
import time
from typing import Annotated

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import Depends, Header, HTTPException
from sqlalchemy import select

from scout.config import settings
from scout.db import Session
from scout.models import ApiKey, ConsoleToken, User

log = logging.getLogger(__name__)

_hasher = PasswordHasher()
TOKEN_TTL = 7 * 24 * 3600  # 会话 7 天，过期重新登录
KEY_PREFIX = "ska_"

# 登录失败限速：同一用户名 15 分钟内最多 8 次失败
_failures: dict[str, list[float]] = {}
LOCK_WINDOW = 900
LOCK_MAX = 8


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except VerifyMismatchError:
        return False
    except Exception:
        return False


def login_attempts_left(username: str) -> int:
    now = time.time()
    hits = [t for t in _failures.get(username, []) if now - t < LOCK_WINDOW]
    _failures[username] = hits
    return max(0, LOCK_MAX - len(hits))


def record_login_failure(username: str) -> None:
    _failures.setdefault(username, []).append(time.time())


def reset_login_failures(username: str) -> None:
    _failures.pop(username, None)


def jwt_secret() -> str:
    """签名密钥复用 console_tokens 表持久化，重启后已签发的会话不失效。"""
    with Session() as db:
        row = db.get(ConsoleToken, "jwt_secret")
        if row and row.token:
            return row.token
    secret = secrets.token_urlsafe(32)
    with Session.begin() as db:
        db.add(ConsoleToken(purpose="jwt_secret", token=secret, rotated_at=time.time()))
    return secret


def issue_token(user: User) -> str:
    now = int(time.time())
    payload = {"sub": user.id, "role": user.role, "iat": now, "exp": now + TOKEN_TTL}
    return jwt.encode(payload, jwt_secret(), algorithm="HS256")


def _user_from_jwt(token: str) -> User | None:
    try:
        payload = jwt.decode(token, jwt_secret(), algorithms=["HS256"])
    except Exception:
        return None
    with Session() as db:
        user = db.get(User, payload.get("sub"))
        if user and user.is_active:
            return user
    return None


def _user_from_api_key(token: str) -> User | None:
    if not token.startswith(KEY_PREFIX):
        return None
    digest = hashlib.sha256(token.encode()).hexdigest()
    with Session.begin() as db:
        row = db.scalar(select(ApiKey).where(ApiKey.key_hash == digest, ApiKey.revoked.is_(False)))
        if not row:
            return None
        row.last_used_at = time.time()
        user = db.get(User, row.user_id)
        return user if user and user.is_active else None


def user_from_credential(token: str) -> User | None:
    return _user_from_jwt(token) or _user_from_api_key(token)


def new_api_key(user_id: str, name: str) -> tuple[str, dict]:
    """返回 (明文一次, 记录摘要)；明文 sha256 落库，不存原文。"""
    plain = KEY_PREFIX + secrets.token_urlsafe(24)
    digest = hashlib.sha256(plain.encode()).hexdigest()
    with Session.begin() as db:
        row = ApiKey(user_id=user_id, name=name[:80], prefix=plain[:10], key_hash=digest, created_at=time.time())
        db.add(row)
        db.flush()
        info = {"id": row.id, "name": row.name, "prefix": row.prefix, "created_at": row.created_at}
    return plain, info


def user_record(user: User) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name or user.username,
        "role": user.role,
        "is_active": user.is_active,
        "created_at": user.created_at,
    }


def principal(authorization: Annotated[str | None, Header()] = None) -> User | str:
    """统一入口：JWT 或个人 API 密钥 → 用户；展示令牌 → "display"。"""
    token = (authorization or "").removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(401, "需要登录")
    user = user_from_credential(token)
    if user:
        return user
    display_value = settings().display_token
    if display_value and secrets.compare_digest(token, display_value):
        return "display"
    raise HTTPException(401, "登录已过期或凭证无效，请重新登录")


def screen(principal=Depends(principal)):
    """大屏只读接口：登录用户或展示令牌皆可。"""
    return principal


def current_user(p=Depends(principal)) -> User:
    if p == "display":
        # 展示令牌认得，但没有管理权限：认证通过、授权不足
        raise HTTPException(403, "展示令牌仅能查看大屏，请用账号登录")
    return p


def require_admin(u=Depends(current_user)) -> User:
    if u.role != "admin":
        raise HTTPException(403, "此操作需要管理员权限")
    return u


def ensure_bootstrap() -> None:
    """首次启动种子系统管理员；此后完全由 users 表管理，.env 仅在空库时生效。"""
    with Session() as db:
        if db.scalar(select(User).limit(1)):
            return
    username = settings().admin_username.strip() or "admin"
    with Session.begin() as db:
        exists = db.scalar(select(User).where(User.username == username).limit(1))
        if exists:
            return
        db.add(
            User(
                username=username,
                password_hash=hash_password(settings().admin_password),
                display_name="系统管理员",
                role="admin",
                created_at=time.time(),
            )
        )
    log.warning("已创建系统管理员账号 %s（首次启动种子，请在管理台及时修改密码）", username)
