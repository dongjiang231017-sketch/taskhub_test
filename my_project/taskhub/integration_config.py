"""
第三方 API 密钥运行时解析：优先「后台 · 第三方集成密钥」数据库记录，
未填写则回退 django.conf.settings（环境变量 + core/*_secrets.py）。
"""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.db.utils import OperationalError, ProgrammingError


class _IntegrationSecretFallback:
    """表未迁移或数据库异常时回退，全部走 settings / 环境变量。"""

    telegram_bot_token = ""
    twitter_bearer_token = ""
    apify_api_token = ""
    apify_instagram_actor_id = ""
    apify_instagram_timeout_sec = None
    apify_twitter_follow_actor_id = ""
    apify_twitter_repost_actor_id = ""
    apify_twitter_timeout_sec = None
    apify_twitter_following_max_results = None
    apify_twitter_auth_token = ""
    apify_twitter_ct0 = ""
    apify_tiktok_actor_id = ""
    apify_tiktok_timeout_sec = None
    apify_tiktok_results_per_page = None


def _row() -> Any:
    from .models import IntegrationSecretConfig

    try:
        return IntegrationSecretConfig.get()
    except (ProgrammingError, OperationalError):
        return _IntegrationSecretFallback()


def get_telegram_bot_token() -> str:
    v = (_row().telegram_bot_token or "").strip()
    if v:
        return v
    return (getattr(settings, "TELEGRAM_BOT_TOKEN", "") or "").strip()


def get_twitter_bearer_token() -> str:
    v = (_row().twitter_bearer_token or "").strip()
    if v:
        return v
    return (getattr(settings, "TWITTER_BEARER_TOKEN", "") or "").strip()


def get_apify_api_token() -> str:
    tokens = get_apify_api_tokens()
    return tokens[0] if tokens else ""


def get_apify_api_tokens() -> list[str]:
    tokens: list[str] = []
    for value in (
        (_row().apify_api_token or "").strip(),
        (getattr(settings, "APIFY_API_TOKEN", "") or "").strip(),
    ):
        if value and value not in tokens:
            tokens.append(value)
    return tokens


def get_apify_instagram_actor_id() -> str:
    v = (_row().apify_instagram_actor_id or "").strip()
    if v:
        return v
    return str(
        getattr(settings, "APIFY_INSTAGRAM_ACTOR_ID", "apify/instagram-profile-scraper") or ""
    ).strip()


def get_apify_instagram_timeout_sec() -> int:
    r = _row()
    if r.apify_instagram_timeout_sec is not None:
        v = int(r.apify_instagram_timeout_sec)
        return max(30, min(v, 300))
    v = int(getattr(settings, "APIFY_INSTAGRAM_TIMEOUT_SEC", 120) or 120)
    return max(30, min(v, 300))


def get_apify_twitter_follow_actor_id() -> str:
    v = (_row().apify_twitter_follow_actor_id or "").strip()
    if v:
        return v
    return str(
        getattr(settings, "APIFY_TWITTER_FOLLOW_ACTOR_ID", "automation-lab/twitter-scraper") or ""
    ).strip()


def get_apify_twitter_repost_actor_id() -> str:
    v = (_row().apify_twitter_repost_actor_id or "").strip()
    if v:
        return v
    return str(
        getattr(settings, "APIFY_TWITTER_REPOST_ACTOR_ID", "api-ninja/x-twitter-replies-retweets-scraper") or ""
    ).strip()


def get_apify_twitter_timeout_sec() -> int:
    r = _row()
    if r.apify_twitter_timeout_sec is not None:
        v = int(r.apify_twitter_timeout_sec)
        return max(30, min(v, 600))
    v = int(getattr(settings, "APIFY_TWITTER_TIMEOUT_SEC", 180) or 180)
    return max(30, min(v, 600))


def get_apify_twitter_following_max_results() -> int:
    r = _row()
    if r.apify_twitter_following_max_results is not None:
        v = int(r.apify_twitter_following_max_results)
        return max(50, min(v, 10000))
    v = int(getattr(settings, "APIFY_TWITTER_FOLLOWING_MAX_RESULTS", 2000) or 2000)
    return max(50, min(v, 10000))


def get_apify_twitter_auth_token() -> str:
    v = (_row().apify_twitter_auth_token or "").strip()
    if v:
        return v
    return (getattr(settings, "APIFY_TWITTER_AUTH_TOKEN", "") or "").strip()


def get_apify_twitter_ct0() -> str:
    v = (_row().apify_twitter_ct0 or "").strip()
    if v:
        return v
    return (getattr(settings, "APIFY_TWITTER_CT0", "") or "").strip()


def get_apify_tiktok_actor_id() -> str:
    v = (_row().apify_tiktok_actor_id or "").strip()
    if v:
        return v
    return str(getattr(settings, "APIFY_TIKTOK_ACTOR_ID", "clockworks/tiktok-scraper") or "").strip()


def get_apify_tiktok_timeout_sec() -> int:
    r = _row()
    if r.apify_tiktok_timeout_sec is not None:
        v = int(r.apify_tiktok_timeout_sec)
        return max(60, min(v, 600))
    v = int(getattr(settings, "APIFY_TIKTOK_TIMEOUT_SEC", 180) or 180)
    return max(60, min(v, 600))


def get_apify_tiktok_results_per_page() -> int:
    r = _row()
    if r.apify_tiktok_results_per_page is not None:
        v = int(r.apify_tiktok_results_per_page)
        return max(10, min(v, 200))
    v = int(getattr(settings, "APIFY_TIKTOK_RESULTS_PER_PAGE", 60) or 60)
    return max(10, min(v, 200))
