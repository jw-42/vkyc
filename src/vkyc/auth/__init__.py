import base64
import hashlib
import hmac
import os
import time
from functools import wraps
from typing import Any, cast
from urllib.parse import urlencode

import jwt

from vkyc.auth.types import AuthContext, JwtPayload, SecretCacheEntry, VkLaunchParams
from vkyc.errors import ForbiddenError, UnauthorizedError
from vkyc.logger import get_logger
from vkyc.types import Context, Event, GatewayResponse, Handler

log = get_logger(__name__)

SECRET_CACHE: dict[str, SecretCacheEntry] = {}
SECRET_CACHE_TTL = 300

JWT_ALGORITHM = "HS256"
JWT_DEFAULT_TTL = 86400
VK_LAUNCH_PARAMS_MAX_AGE = 3600


def get_secret(secret_id: str) -> str:
    """Читает секрет из Yandex Secret Manager и кеширует результат."""
    cached = SECRET_CACHE.get(secret_id)
    if cached and cached["expires"] > time.time():
        return cached["value"]

    value = os.environ[secret_id]
    SECRET_CACHE[secret_id] = {"value": value, "expires": time.time() + SECRET_CACHE_TTL}
    return value


def jwt_secret() -> str:
    """Обёртка над `get_secret()` для JWT-секрета."""
    return get_secret(os.environ["JWT_SECRET_ENV"])


def vk_secret_key() -> str:
    """Обёртка над `get_secret()` для секретного ключа приложения ВКонтакте."""
    return get_secret(os.environ["VK_SECRET_KEY_ENV"])


# ─── VK Mini Apps ─────────────────────────────────────────────────────────────

def verify_vk_launch_params(params: dict[str, object]) -> VkLaunchParams:
    """Проверяет подпись параметров запуска мини-приложения ВКонтакте."""
    secret_id = os.environ["VK_SECRET_KEY_ENV"]
    app_secret = get_secret(secret_id)

    log.debug("VK verify: received keys=%r", sorted(params.keys()))

    if app_secret.lstrip().startswith("{"):
        log.warning("Значение должно быть plaintext, а не JSON-объектом", secret_id)

    flat = {k: str(v) for k, v in params.items()}

    sign = flat.pop("sign", None)
    if not sign:
        raise UnauthorizedError("Подпись параметров запуска мини-приложения отсутствует.")

    vk_ts = int(flat.get("vk_ts", 0))
    if abs(time.time() - vk_ts) > VK_LAUNCH_PARAMS_MAX_AGE:
        raise UnauthorizedError("Параметры запуска мини-приложения устарели.")

    vk_pairs = sorted((k, v) for k, v in flat.items() if k.startswith("vk_"))
    check_string = urlencode(vk_pairs)

    expected = (
        base64.urlsafe_b64encode(
            hmac.new(app_secret.encode(), check_string.encode(), hashlib.sha256).digest()
        )
        .rstrip(b"=")
        .decode()
    )

    if not hmac.compare_digest(expected, sign):
        log.warning(
            "Подпись параметров запуска мини-приложения не совпала: "
            "vk_keys=%r check_string=%r expected=%r received_sign=%r",
            sorted(k for k, _ in vk_pairs),
            check_string,
            expected,
            sign,
        )
        raise UnauthorizedError("Не удалось проверить подпись параметров запуска мини-приложения.")

    return cast(VkLaunchParams, flat)


# ─── JWT ──────────────────────────────────────────────────────────────────────

def generate_token(
    user_id: str,
    role: str,
    group_id: str | None = None,
    group_role: str | None = None,
) -> str:
    ttl = int(os.environ.get("JWT_TTL_SECONDS", JWT_DEFAULT_TTL))
    now = int(time.time())
    payload: JwtPayload = {"sub": user_id, "role": role, "iat": now, "exp": now + ttl}
    if group_id:
        payload["group_id"] = group_id
        payload["group_role"] = group_role or "none"
    return jwt.encode(cast(dict[str, Any], payload), jwt_secret(), algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> JwtPayload:
    """Декодирует и верифицирует JWT-токен."""
    try:
        return cast(JwtPayload, jwt.decode(token, jwt_secret(), algorithms=[JWT_ALGORITHM]))
    except jwt.ExpiredSignatureError:
        raise UnauthorizedError("Срок действия ключа доступа истёк.")
    except jwt.InvalidTokenError:
        raise UnauthorizedError("Недействительный ключ доступа.")


# ─── Декораторы ───────────────────────────────────────────────────────────────

def auth_ctx(event: Event) -> AuthContext:
    """Извлекает контекст авторизатора из события."""
    authorizer = event.get("requestContext", {}).get("authorizer", {})
    ctx = authorizer.get("context") or authorizer
    log.debug("auth ctx=%r", ctx)
    return cast(AuthContext, ctx)


def require_auth(handler: Handler) -> Handler:
    """Извлекает текущего пользователя из контекста авторизатора и добавляет в событие."""
    @wraps(handler)
    def wrapper(event: Event, context: Context) -> GatewayResponse:
        ctx = auth_ctx(event)
        if not ctx.get("user_id"):
            raise UnauthorizedError("Необходима авторизация.")
        event["current_user"] = ctx
        return handler(event, context)

    return wrapper


def require_admin(handler: Handler) -> Handler:
    """Требует роль `admin` из контекста авторизатора."""
    @wraps(handler)
    def wrapper(event: Event, context: Context) -> GatewayResponse:
        ctx = auth_ctx(event)
        if not ctx.get("user_id"):
            raise UnauthorizedError("Необходима авторизация.")
        if ctx.get("role") != "admin":
            raise ForbiddenError("Недостаточно прав для выполнения этого действия.")
        event["current_user"] = ctx
        return handler(event, context)

    return wrapper
