"""TikTok 用户名规范化；从分享链接解析视频 ID（供转发校验）。"""

from __future__ import annotations

import re


def normalize_tiktok_username(raw: str | None) -> str:
    """从 @handle、完整主页或带 video 的 URL 中提取 TikTok 用户名（不含 @）。"""
    if not raw:
        return ""
    s = str(raw).strip()
    if not s:
        return ""
    low = s.lower()
    if "tiktok.com" in low:
        u = s.split("?")[0].split("#")[0].rstrip("/")
        m = re.search(r"tiktok\.com/@([^/?#]+)", u, re.I)
        if m:
            return m.group(1).strip().lstrip("@")
    return s.lstrip("@").strip()


def extract_tiktok_video_id_from_url(url: str | None) -> str | None:
    """
    从标准分享链接解析数字视频 ID，例如：
    https://www.tiktok.com/@someone/video/7123456789012345678
    """
    if not url or not isinstance(url, str):
        return None
    s = url.strip()
    m = re.search(r"/video/(\d{10,25})(?:[^\d]|$)", s)
    if m:
        return m.group(1)
    m = re.search(r"tiktok\.com/t/(\d{10,25})(?:[^\d]|$)", s, re.I)
    if m:
        return m.group(1)
    return None
