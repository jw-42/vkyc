import base64
import hashlib
import hmac
import os
import time
from functools import wraps
from typing import Optional
from urllib.parse import urlencode

import jwt

from vkyc.errors import ForbiddenError, UnauthorizedError
from vkyc.logger import get_logger

log = get_logger(__name__)

SECRET_CACHE: dict = {}
SECRET_CACHE_TTL = 300  # 5 минут

JWT_ALGORITHM = "HS256"
JWT_DEFAULT_TTL = 86400  # 24 часа
VK_LAUNCH_PARAMS_MAX_AGE = 3600  # 1 час — защита от replay-атак


def get_secret(secret_id: str) -> str:
    """Читает секрет из env-переменной, инжектированной из секретного хранилища."""
    cached = SECRET_CACHE.get(secret_id)
    if cached and cached["expires"] > time.time():
        return cached["value"]

    value = os.environ[secret_id]
    SECRET_CACHE[secret_id] = {"value": value, "expires": time.time() + SECRET_CACHE_TTL}
    return value


def jwt_secret() -> str:
    return get_secret(os.environ["JWT_SECRET_SECRET_NAME"])


def vk_secret_key() -> str:
    """Защищённый ключ VK-приложения — подписывает launch params (HMAC-SHA256,
    см. verify_vk_launch_params)."""
    return get_secret(os.environ["VK_SECRET_KEY_SECRET_NAME"])


# ─── VK Mini Apps ─────────────────────────────────────────────────────────────

def verify_vk_launch_params(params: dict) -> dict:
    """
    Верифицирует подпись VK Mini Apps launch params.
    Принимает dict параметров (от VKWebAppGetLaunchParams через VK Bridge).
    Возвращает dict всех vk_* параметров без поля sign.
    Поднимает UnauthorizedError при невалидной подписи.
    """
    secret_id = os.environ["VK_SECRET_KEY_SECRET_NAME"]
    app_secret = get_secret(secret_id)

    log.debug("VK verify: received keys=%r", sorted(params.keys()))

    # Проверка на случай, если секрет хранится в secret manager как JSON-объект,
    # а не как plaintext — в этом случае HMAC будет вычислен от неверного ключа.
    if app_secret.lstrip().startswith("{"):
        log.warning(
            "VK секрет похож на JSON-объект (secret_id=%r). "
            "Убедитесь, что в хранилище секретов лежит сырая строка (plaintext), "
            "а не обёртка вида {\"key\": \"value\"}.",
            secret_id,
        )

    # Все значения приводим к str, как они приходят из URL-параметров VK
    flat = {k: str(v) for k, v in params.items()}

    sign = flat.pop("sign", None)
    if not sign:
        raise UnauthorizedError("отсутствует подпись VK")

    vk_ts = int(flat.get("vk_ts", 0))
    if abs(time.time() - vk_ts) > VK_LAUNCH_PARAMS_MAX_AGE:
        raise UnauthorizedError("устаревшие параметры VK")

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
            "VK подпись не совпала: "
            "vk_keys=%r check_string=%r expected=%r received_sign=%r",
            sorted(k for k, _ in vk_pairs),
            check_string,
            expected,
            sign,
        )
        raise UnauthorizedError("Не удалось проверить подпись параметров запуска мини-приложения.")

    return flat


# ─── JWT ──────────────────────────────────────────────────────────────────────

def generate_token(
    user_id: str,
    role: str,
    group_id: Optional[str] = None,
    group_role: Optional[str] = None,
) -> str:
    ttl = int(os.environ.get("JWT_TTL_SECONDS", JWT_DEFAULT_TTL))
    now = int(time.time())
    payload = {"sub": user_id, "role": role, "iat": now, "exp": now + ttl}
    if group_id:
        payload["group_id"] = group_id
        payload["group_role"] = group_role or "none"
    return jwt.encode(payload, jwt_secret(), algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    """Декодирует и верифицирует JWT. Используется авторизатором API Gateway."""
    try:
        return jwt.decode(token, jwt_secret(), algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise UnauthorizedError("токен истёк")
    except jwt.InvalidTokenError:
        raise UnauthorizedError("недействительный токен")


# ─── Декораторы ───────────────────────────────────────────────────────────────
# Авторизатор API Gateway уже проверил JWT и is_blocked до вызова функции.
# Декораторы только читают готовый контекст из event["requestContext"]["authorizer"]["context"].

def auth_ctx(event: dict) -> dict:
    """
    Извлекает контекст авторизатора из event.
    Yandex API Gateway кладёт context авторизатора напрямую в
    requestContext.authorizer (не в requestContext.authorizer.context как AWS).
    """
    authorizer = event.get("requestContext", {}).get("authorizer", {})
    # Yandex: context — плоский dict прямо в authorizer
    # AWS:    context вложен в authorizer["context"]
    ctx = authorizer.get("context") or authorizer
    log.debug("auth ctx=%r", ctx)
    return ctx


def require_auth(handler):
    """Извлекает current_user из контекста авторизатора и добавляет в event."""
    @wraps(handler)
    def wrapper(event, context):
        ctx = auth_ctx(event)
        if not ctx.get("user_id"):
            raise UnauthorizedError("требуется авторизация")
        event["current_user"] = ctx
        return handler(event, context)

    return wrapper


def require_admin(handler):
    """Требует роль admin из контекста авторизатора."""
    @wraps(handler)
    def wrapper(event, context):
        ctx = auth_ctx(event)
        if not ctx.get("user_id"):
            raise UnauthorizedError("требуется авторизация")
        if ctx.get("role") != "admin":
            raise ForbiddenError("недостаточно прав")
        event["current_user"] = ctx
        return handler(event, context)

    return wrapper
