"""通过 Apify 校验 Twitter / X 的关注与转发。"""

from __future__ import annotations

import json
import logging
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .integration_config import (
    get_apify_api_token,
    get_apify_twitter_auth_token,
    get_apify_twitter_ct0,
    get_apify_twitter_follow_actor_id,
    get_apify_twitter_following_max_results,
    get_apify_twitter_repost_actor_id,
    get_apify_twitter_timeout_sec,
)
from .twitter_client import extract_tweet_id_from_url, normalize_twitter_username

logger = logging.getLogger(__name__)


def apify_twitter_follow_configured() -> bool:
    return bool(get_apify_api_token())


def apify_twitter_repost_configured() -> bool:
    return bool(get_apify_api_token())


def _actor_path_segment(raw: str) -> str:
    if "~" in raw:
        return raw
    if "/" in raw:
        return raw.replace("/", "~", 1)
    return raw


def _apify_post(actor_id: str, payload_obj: dict[str, Any]) -> tuple[Any, str | None]:
    token = get_apify_api_token().strip()
    if not token:
        return None, "未配置 APIFY_API_TOKEN"
    actor_seg = _actor_path_segment(actor_id)
    timeout_sec = get_apify_twitter_timeout_sec()
    qs = urlencode({"token": token, "timeout": str(timeout_sec)})
    url = f"https://api.apify.com/v2/acts/{actor_seg}/run-sync-get-dataset-items?{qs}"
    payload = json.dumps(payload_obj).encode("utf-8")
    req = Request(
        url,
        data=payload,
        method="POST",
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    client_timeout = timeout_sec + 90
    try:
        with urlopen(req, timeout=client_timeout) as resp:
            raw = resp.read().decode("utf-8", errors="ignore")
    except HTTPError as e:
        try:
            body = json.loads(e.read().decode("utf-8", errors="ignore"))
        except json.JSONDecodeError:
            body = {}
        msg = body.get("error", {}).get("message") if isinstance(body.get("error"), dict) else str(body)
        return None, msg or f"Apify 请求失败 HTTP {e.code}"
    except URLError as e:
        return None, f"Apify 请求失败：{e.reason}"
    except OSError as e:
        return None, f"Apify 请求失败：{e}"
    try:
        data = json.loads(raw) if raw else None
    except json.JSONDecodeError:
        return None, "Apify 返回非 JSON"
    if isinstance(data, dict) and data.get("error"):
        err = data["error"]
        msg = err.get("message") if isinstance(err, dict) else str(err)
        return None, msg or "Apify 返回错误"
    return data, None


def _humanize_apify_twitter_error(err: str | None, *, action_label: str) -> str:
    msg = str(err or "").strip()
    low = msg.lower()
    if not msg:
        return f"暂时无法完成 Twitter {action_label}校验，请稍后再试。"
    if "user was not found or authentication token is not valid" in low or "invalid api token" in low:
        return "Twitter Apify 校验服务鉴权失败，请联系管理员检查 Apify Token。"
    if "auth_token" in low or "ct0" in low or "cookie" in low:
        return "Twitter Apify 校验缺少可用 Cookie，请联系管理员补充 auth_token / ct0。"
    if "rate limit" in low or "too many requests" in low or "quota" in low:
        return f"Twitter {action_label}校验服务繁忙，请稍后再试。"
    if "private" in low:
        return "该 Twitter 账号可能不可公开校验，请稍后再试。"
    if "network" in low or "timeout" in low or "timed out" in low or "apify 请求失败" in msg:
        return f"Twitter {action_label}校验服务网络异常，请稍后再试。"
    return f"暂时无法完成 Twitter {action_label}校验，请稍后再试。"


def apify_twitter_error_is_service_side(err: str | None) -> bool:
    low = str(err or "").strip().lower()
    if not low:
        return True
    return any(
        token in low
        for token in (
            "user was not found or authentication token is not valid",
            "invalid api token",
            "auth_token",
            "ct0",
            "cookie",
            "rate limit",
            "too many requests",
            "quota",
            "timeout",
            "timed out",
            "network",
            "apify 请求失败",
            "non json",
            "返回非 json",
            "返回格式异常",
        )
    )


def _candidate_username_values(row: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for key in ("username", "userName", "screen_name", "screenName", "handle"):
        val = row.get(key)
        if val:
            values.append(str(val))
    user = row.get("user")
    if isinstance(user, dict):
        for key in ("username", "userName", "screen_name", "screenName", "handle"):
            val = user.get(key)
            if val:
                values.append(str(val))
    return values


def user_follows_username_via_apify(source_username: str, target_username: str) -> tuple[bool, str | None]:
    source = normalize_twitter_username(source_username)
    target = normalize_twitter_username(target_username)
    if not source or not target:
        return False, "无法解析 Twitter 用户名。"
    actor_id = get_apify_twitter_follow_actor_id()
    payload: dict[str, Any]
    auth_token = get_apify_twitter_auth_token().strip()
    ct0 = get_apify_twitter_ct0().strip()
    if "automation-lab/twitter-scraper" in actor_id:
        payload = {
            "mode": "following",
            "usernames": [source],
            "maxResults": get_apify_twitter_following_max_results(),
        }
        cookie_parts: list[str] = []
        if auth_token:
            cookie_parts.append(f"auth_token={auth_token}")
        if ct0:
            cookie_parts.append(f"ct0={ct0}")
        if cookie_parts:
            payload["twitterCookie"] = "; ".join(cookie_parts)
    else:
        payload = {
            "startUrls": [f"https://x.com/{source}/following"],
            "maxResults": get_apify_twitter_following_max_results(),
        }
        if auth_token:
            payload["authToken"] = auth_token
        if ct0:
            payload["ct0"] = ct0
    data, err = _apify_post(actor_id, payload)
    if err:
        logger.warning("Twitter follow verification via Apify failed for %s -> %s: %s", source, target, err)
        return False, _humanize_apify_twitter_error(err, action_label="关注")
    if not isinstance(data, list):
        return False, _humanize_apify_twitter_error("Apify 返回格式异常", action_label="关注")
    want = target.lower()
    for row in data:
        if not isinstance(row, dict):
            continue
        for candidate in _candidate_username_values(row):
            if normalize_twitter_username(candidate).lower() == want:
                return True, None
    return False, "并未检测到关注，请先完成关注后再试。"


def user_retweeted_tweet_via_apify(tweet_url: str, username: str) -> tuple[bool, str | None]:
    want = normalize_twitter_username(username)
    tweet_id = extract_tweet_id_from_url(tweet_url)
    if not want or not tweet_id:
        return False, "任务要求暂时无法校验，请联系管理员处理。"
    payload = {
        "startUrls": [tweet_url],
        "urls": [tweet_url],
        "category": "checkRetweet",
        "retweetCheckUsername": want,
    }
    data, err = _apify_post(get_apify_twitter_repost_actor_id(), payload)
    if err:
        logger.warning("Twitter repost verification via Apify failed for %s on %s: %s", want, tweet_id, err)
        return False, _humanize_apify_twitter_error(err, action_label="转发")
    rows = data if isinstance(data, list) else [data]
    for row in rows:
        if not isinstance(row, dict):
            continue
        for key in ("isRetweeted", "is_retweeted", "retweeted", "retweetCheckResult"):
            val = row.get(key)
            if isinstance(val, bool):
                return (val, None) if val else (False, "并未检测到转发，请先完成转发后再试。")
        result = row.get("result")
        if isinstance(result, dict):
            for key in ("isRetweeted", "is_retweeted", "retweeted"):
                val = result.get(key)
                if isinstance(val, bool):
                    return (val, None) if val else (False, "并未检测到转发，请先完成转发后再试。")
    return False, _humanize_apify_twitter_error("Apify 返回格式异常", action_label="转发")
