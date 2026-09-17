from typing import NotRequired, TypedDict


class SecretCacheEntry(TypedDict):
    value: str
    expires: float


class JwtPayload(TypedDict):
    sub: str
    role: str
    iat: int
    exp: int
    group_id: NotRequired[str]
    group_role: NotRequired[str]


class AuthContext(TypedDict):
    """Контекст авторизатора: `event["current_user"]` после `require_auth`/`require_admin`."""
    user_id: str
    role: str
    group_id: NotRequired[str]
    group_role: NotRequired[str]


class VkLaunchParams(TypedDict, total=False):
    """Параметры запуска мини-приложения ВКонтакте."""
    vk_access_token_settings: str
    vk_app_id: str
    vk_are_notifications_enabled: str
    vk_chat_id: str
    vk_group_id: str
    vk_has_profile_button: str
    vk_is_app_user: str
    vk_is_favorite: str
    vk_is_play_machine: str
    vk_is_recommended: str
    vk_is_widescreen: str
    vk_language: str
    vk_platform: str
    vk_profile_id: str
    vk_ref: str
    vk_request_key: str
    vk_testing_group_id: str
    vk_ts: str
    vk_user_id: str
    vk_viewer_group_role: str
