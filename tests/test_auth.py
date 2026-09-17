import base64
import hashlib
import hmac
import time
from urllib.parse import urlencode

import jwt as pyjwt
import pytest

from vkyc.auth import (
    auth_ctx,
    decode_token,
    generate_token,
    require_admin,
    require_auth,
    verify_vk_launch_params,
)
from vkyc.errors import ForbiddenError, UnauthorizedError

VK_SECRET = "vk-test-secret"
JWT_SECRET = "jwt-test-secret-long-enough-for-hs256-minimum"


@pytest.fixture(autouse=True)
def secrets_env(monkeypatch):
    monkeypatch.setenv("VK_SECRET_KEY_ENV", "VK_SECRET_KEY_VALUE")
    monkeypatch.setenv("VK_SECRET_KEY_VALUE", VK_SECRET)
    monkeypatch.setenv("JWT_SECRET_ENV", "JWT_SECRET_VALUE")
    monkeypatch.setenv("JWT_SECRET_VALUE", JWT_SECRET)
    # get_secret() caches by secret_id across tests (module-level dict) — сбрасываем.
    from vkyc.auth import SECRET_CACHE
    SECRET_CACHE.clear()


def sign_params(params: dict) -> dict:
    pairs = sorted((k, v) for k, v in params.items() if k.startswith("vk_"))
    check_string = urlencode(pairs)
    sign = base64.urlsafe_b64encode(
        hmac.new(VK_SECRET.encode(), check_string.encode(), hashlib.sha256).digest()
    ).rstrip(b"=").decode()
    return {**params, "sign": sign}


def test_verify_vk_launch_params_accepts_valid_signature():
    params = sign_params({"vk_user_id": "1", "vk_ts": str(int(time.time()))})
    result = verify_vk_launch_params(params)
    assert result["vk_user_id"] == "1"
    assert "sign" not in result


def test_verify_vk_launch_params_rejects_bad_signature():
    params = sign_params({"vk_user_id": "1", "vk_ts": str(int(time.time()))})
    params["sign"] = "garbage"
    with pytest.raises(UnauthorizedError):
        verify_vk_launch_params(params)


def test_verify_vk_launch_params_rejects_missing_sign():
    with pytest.raises(UnauthorizedError):
        verify_vk_launch_params({"vk_user_id": "1"})


def test_verify_vk_launch_params_rejects_stale_timestamp():
    old_ts = str(int(time.time()) - 7200)
    params = sign_params({"vk_user_id": "1", "vk_ts": old_ts})
    with pytest.raises(UnauthorizedError):
        verify_vk_launch_params(params)


def test_generate_and_decode_token_roundtrip():
    token = generate_token("42", "admin")
    payload = decode_token(token)
    assert payload["sub"] == "42"
    assert payload["role"] == "admin"
    assert "group_id" not in payload


def test_generate_token_carries_group_context():
    token = generate_token("42", "user", group_id="100", group_role="editor")
    payload = decode_token(token)
    assert payload["group_id"] == "100"
    assert payload["group_role"] == "editor"


def test_decode_token_rejects_invalid_token():
    with pytest.raises(UnauthorizedError):
        decode_token("not-a-token")


def test_decode_token_rejects_expired_token():
    payload = {"sub": "1", "role": "user", "iat": 0, "exp": 1}
    token = pyjwt.encode(payload, JWT_SECRET, algorithm="HS256")
    with pytest.raises(UnauthorizedError):
        decode_token(token)


def test_auth_ctx_reads_yandex_flat_shape():
    event = {"requestContext": {"authorizer": {"user_id": "1", "role": "admin"}}}
    assert auth_ctx(event) == {"user_id": "1", "role": "admin"}


def test_auth_ctx_reads_aws_nested_shape():
    event = {"requestContext": {"authorizer": {"context": {"user_id": "1"}}}}
    assert auth_ctx(event) == {"user_id": "1"}


def test_require_auth_passes_current_user_through():
    @require_auth
    def handler(event, context):
        return event["current_user"]

    event = {"requestContext": {"authorizer": {"user_id": "1", "role": "user"}}}
    assert handler(event, None) == {"user_id": "1", "role": "user"}


def test_require_auth_rejects_missing_user():
    @require_auth
    def handler(event, context):
        return "should not run"

    with pytest.raises(UnauthorizedError):
        handler({"requestContext": {"authorizer": {}}}, None)


def test_require_admin_rejects_non_admin():
    @require_admin
    def handler(event, context):
        return "should not run"

    event = {"requestContext": {"authorizer": {"user_id": "1", "role": "user"}}}
    with pytest.raises(ForbiddenError):
        handler(event, None)


def test_require_admin_allows_admin():
    @require_admin
    def handler(event, context):
        return "ok"

    event = {"requestContext": {"authorizer": {"user_id": "1", "role": "admin"}}}
    assert handler(event, None) == "ok"
