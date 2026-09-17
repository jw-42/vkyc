"""
Протокол платёжных уведомлений о подписках ВКонтакте (не «VK Pay» — другой,
несвязанный продукт VK). VK шлёт server-to-server POST-уведомления
(get_subscription, subscription_status_change) на callback-URL из настроек
приложения. Тело — urlencoded пары key=value (не JSON), подпись — параметр
sig: md5 от конкатенации отсортированных по ключу пар "k=v" без разделителей
плюс секретный ключ приложения (`vkyc.auth.vk_secret_key`).

Ответ ВСЕГДА HTTP 200; успех/ошибка различаются телом:
{"response": {...}} либо {"error": {"error_code", "error_msg", "critical"}}.
critical=false => VK повторит уведомление позже.

Docs: https://dev.vk.com/ru/api/payments/subscriptions/vk

Перенесено из forms/api (decisions/054 в forms repo) — только протокол
(разбор, подпись, конверт ответа), без сущности "подписка" как таковой:
каталог тарифов, атрибуция сообществу и метрики выручки — форма-специфичны
и остаются в forms/api.
"""

import base64
import hashlib
import hmac
from typing import TypedDict
from urllib.parse import parse_qsl

from vkyc.auth import vk_secret_key
from vkyc.types import Event

# Коды ошибок протокола платёжных уведомлений VK.
ERR_COMMON = 1          # общая ошибка (critical=false => ретрай)
ERR_TEMPORARY = 2       # временная ошибка БД (critical=false => ретрай)
ERR_BAD_SIG = 10        # подпись не совпала
ERR_BAD_REQUEST = 11    # параметры не соответствуют спецификации
ERR_ITEM_NOT_FOUND = 20 # товара/подписки не существует


def advance_next_bill_time(next_bill_time: int, period_days: int) -> int:
    """
    Сдвигает next_bill_time на один период тарифа вперёд — используется
    суточной развёрткой platform_stats/snapshot в forms/api при обнаружении
    продления (decisions/038 в forms repo): VK не шлёт уведомлений о
    регулярных списаниях, поэтому следующая дата пересчитывается, а не
    берётся из уведомления.
    """
    return next_bill_time + period_days * 86400


def parse_notification(event: Event) -> dict[str, str]:
    """Разбирает urlencoded-тело платёжного уведомления из события гейтвея."""
    raw_body = event.get("body") or ""
    body = base64.b64decode(raw_body).decode() if event.get("isBase64Encoded") else raw_body
    return dict(parse_qsl(body, keep_blank_values=True))


def verify_payment_sig(params: dict[str, str]) -> bool:
    """
    Проверяет MD5-подпись платёжного уведомления. Значения params должны
    быть уже URL-раскодированы (parse_qsl это делает).
    """
    received = params.get("sig", "")
    if not received:
        return False
    joined = "".join(f"{k}={v}" for k, v in sorted(params.items()) if k != "sig")
    expected = hashlib.md5((joined + vk_secret_key()).encode()).hexdigest()
    return hmac.compare_digest(expected, received)


def strip_test_suffix(notification_type: str) -> tuple[str, bool]:
    """"get_subscription_test" -> ("get_subscription", True)."""
    if notification_type.endswith("_test"):
        return notification_type[: -len("_test")], True
    return notification_type, False


class PaymentErrorDetail(TypedDict):
    error_code: int
    error_msg: str
    critical: bool


class PaymentErrorEnvelope(TypedDict):
    """Тело ответа при ошибке в протоколе платёжных уведомлений VK."""
    error: PaymentErrorDetail


def vk_error(code: int, msg: str, critical: bool) -> PaymentErrorEnvelope:
    return {"error": {"error_code": code, "error_msg": msg, "critical": critical}}
