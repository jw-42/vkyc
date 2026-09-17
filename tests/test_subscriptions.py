import base64
import hashlib

import pytest

from vkyc.subscriptions import (
    advance_next_bill_time,
    parse_notification,
    strip_test_suffix,
    verify_payment_sig,
    vk_error,
)

VK_SECRET = "vk-test-secret"


@pytest.fixture(autouse=True)
def secrets_env(monkeypatch):
    monkeypatch.setenv("VK_SECRET_KEY_ENV", "VK_SECRET_KEY_VALUE")
    monkeypatch.setenv("VK_SECRET_KEY_VALUE", VK_SECRET)
    # get_secret() кеширует по secret_id в модульном словаре — сбрасываем.
    from vkyc.auth import SECRET_CACHE
    SECRET_CACHE.clear()


def sign_notification(params: dict) -> dict:
    joined = "".join(f"{k}={v}" for k, v in sorted(params.items()) if k != "sig")
    sig = hashlib.md5((joined + VK_SECRET).encode()).hexdigest()
    return {**params, "sig": sig}


# ─── parse_notification ────────────────────────────────────────────────────────

def test_parse_notification_plain_body():
    event = {"body": "type=get_subscription&app_id=1"}
    assert parse_notification(event) == {"type": "get_subscription", "app_id": "1"}


def test_parse_notification_base64_body():
    raw = "type=get_subscription&app_id=1"
    event = {"body": base64.b64encode(raw.encode()).decode(), "isBase64Encoded": True}
    assert parse_notification(event) == {"type": "get_subscription", "app_id": "1"}


def test_parse_notification_keeps_blank_values():
    event = {"body": "type=get_subscription&pending_cancel="}
    assert parse_notification(event) == {"type": "get_subscription", "pending_cancel": ""}


def test_parse_notification_missing_body():
    assert parse_notification({}) == {}


# ─── verify_payment_sig ─────────────────────────────────────────────────────────

def test_verify_payment_sig_accepts_valid_signature():
    params = sign_notification({"notification_type": "get_subscription", "app_id": "1"})
    assert verify_payment_sig(params) is True


def test_verify_payment_sig_rejects_bad_signature():
    params = sign_notification({"notification_type": "get_subscription", "app_id": "1"})
    params["sig"] = "0" * 32
    assert verify_payment_sig(params) is False


def test_verify_payment_sig_rejects_missing_signature():
    assert verify_payment_sig({"notification_type": "get_subscription"}) is False


def test_verify_payment_sig_ignores_sig_field_itself_when_computing():
    # sig не должен участвовать в конкатенации, из которой считается подпись.
    params = sign_notification({"a": "1", "b": "2"})
    tampered_but_same_sig = {"a": "1", "b": "3", "sig": params["sig"]}
    assert verify_payment_sig(tampered_but_same_sig) is False


# ─── strip_test_suffix ──────────────────────────────────────────────────────────

def test_strip_test_suffix_strips_test_marker():
    assert strip_test_suffix("get_subscription_test") == ("get_subscription", True)


def test_strip_test_suffix_leaves_regular_type_unchanged():
    assert strip_test_suffix("get_subscription") == ("get_subscription", False)


# ─── vk_error ───────────────────────────────────────────────────────────────────

def test_vk_error_envelope_shape():
    assert vk_error(10, "bad sig", False) == {
        "error": {"error_code": 10, "error_msg": "bad sig", "critical": False}
    }


# ─── advance_next_bill_time ─────────────────────────────────────────────────────

def test_advance_next_bill_time_shifts_by_one_period():
    assert advance_next_bill_time(1_000_000, 30) == 1_000_000 + 30 * 86400


def test_advance_next_bill_time_zero_period_is_noop():
    assert advance_next_bill_time(1_000_000, 0) == 1_000_000
