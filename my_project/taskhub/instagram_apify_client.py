"""通过 Apify Store Actor 拉取 Instagram 公开资料，用于简介链接校验。"""

from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .integration_config import (
    get_apify_api_token,
    get_apify_instagram_actor_id,
    get_apify_instagram_timeout_sec,
)
from .instagram_client import (
    instagram_proof_link_too_generic,
    normalize_instagram_username,
    text_contains_proof_link,
)


def apify_instagram_configured() -> bool:
    return bool(get_apify_api_token())


def _actor_path_segment() -> str:
    """REST 路径里 Actor 用 `owner~name`，Store 链接常为 `owner/name`。"""
    raw = get_apify_instagram_actor_id()
    if "~" in raw:
        return raw
    if "/" in raw:
        return raw.replace("/", "~", 1)
    return raw


def _haystack_from_profile_row(row: dict[str, Any]) -> str:
    parts: list[str] = []
    for k in ("biography", "bio", "description"):
        v = row.get(k)
        if v:
            parts.append(str(v))
    for k in ("externalUrl", "external_url", "website", "externalUrlShimmed"):
        v = row.get(k)
        if v:
            parts.append(str(v))
    ex = row.get("externalUrls")
    if isinstance(ex, list):
        for it in ex:
            if isinstance(it, dict):
                for kk in ("url", "lynx_url"):
                    v = it.get(kk)
                    if v:
                        parts.append(str(v))
    return "\n".join(parts)


def fetch_instagram_profile_via_apify(username: str) -> tuple[dict[str, Any] | None, str | None]:
    """
    调用 Apify `run-sync-get-dataset-items`，返回数据集第一条与目标用户名匹配的资料（若无则取首条）。
    """
    if not apify_instagram_configured():
        return None, "未配置 APIFY_API_TOKEN"
    u = normalize_instagram_username(username)
    if not u:
        return None, "无法解析 Instagram 用户名"
    token = get_apify_api_token().strip()
    actor_seg = _actor_path_segment()
    timeout_sec = get_apify_instagram_timeout_sec()
    qs = urlencode({"token": token, "timeout": str(timeout_sec)})
    url = f"https://api.apify.com/v2/acts/{actor_seg}/run-sync-get-dataset-items?{qs}"
    payload = json.dumps({"usernames": [u]}).encode("utf-8")
    req = Request(
        url,
        data=payload,
        method="POST",
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    client_timeout = timeout_sec + 60
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
    if not isinstance(data, list) or not data:
        return None, "Apify 未返回资料（用户名不存在、私密账号或 Actor 无结果）"
    want = u.lower()
    for row in data:
        if not isinstance(row, dict):
            continue
        ru = normalize_instagram_username(row.get("username") or "")
        if ru.lower() == want:
            return row, None
    first = data[0]
    return (first, None) if isinstance(first, dict) else (None, "Apify 返回格式异常")


def profile_contains_proof_via_apify(username: str, proof_url: str) -> tuple[bool, str | None]:
    needle = (proof_url or "").strip()
    if not needle:
        return True, None
    if instagram_proof_link_too_generic(needle):
        return False, "任务要求的链接配置不正确，请联系发布方处理。"
    row, err = fetch_instagram_profile_via_apify(username)
    if err or not row:
        if err and "无法解析" in err:
            return False, "请填写正确的 Instagram 用户名或主页链接。"
        return False, "暂时无法获取账号资料，请稍后再试。"
    hay = _haystack_from_profile_row(row)
    if text_contains_proof_link(hay, needle):
        return True, None
    return False, "并没有在简介里找到要求填写的内容。"
