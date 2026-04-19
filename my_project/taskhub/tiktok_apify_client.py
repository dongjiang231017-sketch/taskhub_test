"""通过 Apify（默认 clockworks/tiktok-scraper）抓取用户 Reposts，校验是否转发过指定视频。"""

from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .integration_config import (
    get_apify_api_token,
    get_apify_tiktok_actor_id,
    get_apify_tiktok_results_per_page,
    get_apify_tiktok_timeout_sec,
)
from .tiktok_client import extract_tiktok_video_id_from_url, normalize_tiktok_username


def apify_tiktok_configured() -> bool:
    return bool(get_apify_api_token())


def _tiktok_actor_path_segment() -> str:
    raw = get_apify_tiktok_actor_id()
    if "~" in raw:
        return raw
    if "/" in raw:
        return raw.replace("/", "~", 1)
    return raw


def _item_references_video_id(item: dict[str, Any], want_id: str) -> bool:
    if str(item.get("id") or "") == want_id:
        return True
    for key in ("webVideoUrl", "url", "shareUrl", "videoUrl", "submittedVideoUrl"):
        val = item.get(key)
        if isinstance(val, str) and f"/video/{want_id}" in val:
            return True
    vid = item.get("video")
    if isinstance(vid, dict) and str(vid.get("id") or "") == want_id:
        return True
    return False


def fetch_user_reposts_dataset_via_apify(username: str) -> tuple[list[dict[str, Any]] | None, str | None]:
    """
    调用 Apify run-sync-get-dataset-items，抓取该用户 profile 的 Reposts 分区若干条。
    """
    if not apify_tiktok_configured():
        return None, "未配置 APIFY_API_TOKEN"
    un = normalize_tiktok_username(username)
    if not un:
        return None, "无法解析 TikTok 用户名"
    token = get_apify_api_token().strip()
    actor_seg = _tiktok_actor_path_segment()
    timeout_sec = get_apify_tiktok_timeout_sec()
    results_per_page = get_apify_tiktok_results_per_page()

    payload_obj: dict[str, Any] = {
        "profiles": [un],
        "profileScrapeSections": ["reposts"],
        "resultsPerPage": results_per_page,
        "profileSorting": "latest",
        "maxFollowersPerProfile": 0,
        "maxFollowingPerProfile": 0,
        "commentsPerPost": 0,
        "topLevelCommentsPerPost": 0,
        "maxRepliesPerComment": 0,
        "proxyCountryCode": "None",
    }
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
    if not isinstance(data, list):
        return None, "Apify 返回格式异常"
    return data, None


def user_reposted_video_via_apify(username: str, target_video_url: str) -> tuple[bool, str | None]:
    """
    在用户 Reposts 列表中查找是否出现目标视频（按 /video/数字ID 匹配）。
    """
    needle = (target_video_url or "").strip()
    if not needle:
        return True, None
    vid = extract_tiktok_video_id_from_url(needle)
    if not vid:
        return False, "任务要求暂时无法校验，请联系发布方处理。"
    rows, err = fetch_user_reposts_dataset_via_apify(username)
    if err or rows is None:
        if err and "无法解析" in err:
            return False, "请填写正确的 TikTok 用户名或主页链接。"
        return False, "暂时无法完成校验，请稍后再试。"
    for row in rows:
        if not isinstance(row, dict):
            continue
        if _item_references_video_id(row, vid):
            return True, None
    return False, "并未检测到转发，请确认已完成转发后再试。"
