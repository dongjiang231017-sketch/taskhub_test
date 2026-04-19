"""Twitter API v2 辅助：校验转发 / 关注（Bearer Token，只读）。"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request


TWITTER_API = "https://api.twitter.com/2"


def normalize_twitter_username(raw: str | None) -> str:
    if not raw:
        return ""
    s = str(raw).strip().lstrip("@")
    return s


def extract_tweet_id_from_url(url: str | None) -> str | None:
    if not url or not isinstance(url, str):
        return None
    m = re.search(r"/status/(\d+)", url)
    return m.group(1) if m else None


def _twitter_get(bearer: str, path: str, params: dict | None = None) -> dict:
    q = urllib.parse.urlencode({k: v for k, v in (params or {}).items() if v is not None})
    url = f"{TWITTER_API}{path}"
    if q:
        url = f"{url}?{q}"
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {bearer}"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise ValueError(f"Twitter API HTTP {e.code}: {body[:500]}") from e


def lookup_user_id_by_username(bearer: str, username: str) -> str | None:
    un = normalize_twitter_username(username)
    if not un:
        return None
    data = _twitter_get(bearer, f"/users/by/username/{urllib.parse.quote(un)}")
    d = data.get("data") or {}
    uid = d.get("id")
    return str(uid) if uid else None


def user_retweeted_tweet(bearer: str, tweet_id: str, username: str) -> bool:
    """检查 username（不含 @）是否出现在该推文的转发用户列表中。"""
    want = normalize_twitter_username(username).lower()
    if not want or not tweet_id:
        return False
    token = None
    while True:
        params: dict[str, str | int] = {"max_results": 100, "user.fields": "username"}
        if token:
            params["pagination_token"] = token
        data = _twitter_get(bearer, f"/tweets/{tweet_id}/retweeted_by", params)
        for u in data.get("data") or []:
            if (u.get("username") or "").lower() == want:
                return True
        token = (data.get("meta") or {}).get("next_token")
        if not token:
            return False


def user_follows_username(bearer: str, source_username: str, target_username: str) -> bool:
    """检查 source 是否关注了 target（均为不含 @ 的 username）。"""
    want = normalize_twitter_username(target_username).lower()
    sid = lookup_user_id_by_username(bearer, source_username)
    if not sid or not want:
        return False
    token = None
    while True:
        params: dict[str, str | int] = {"max_results": 1000, "user.fields": "username"}
        if token:
            params["pagination_token"] = token
        data = _twitter_get(bearer, f"/users/{sid}/following", params)
        for u in data.get("data") or []:
            if (u.get("username") or "").lower() == want:
                return True
        token = (data.get("meta") or {}).get("next_token")
        if not token:
            return False
