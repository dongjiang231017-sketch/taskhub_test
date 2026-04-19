"""YouTube 频道标识规范化与简介页拉取（用于绑定任务校验，无官方 OAuth）。"""

from __future__ import annotations

import re
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

_USER_AGENT = (
    "Mozilla/5.0 (compatible; TaskHubBindingVerify/1.0; +https://www.djangoproject.com/)"
)


def normalize_youtube_channel_identifier(raw: str | None) -> str:
    """
    从用户输入中提取用于访问 /about 的频道标识：@handle、自定义路径、c/user、或 channel/UC… 的 UC 段。
    返回不含 @ 的 handle 或 UC… id；无法识别则返回去空白后的原串（小写 handle 常见）。
    """
    if not raw:
        return ""
    s = str(raw).strip()
    if not s:
        return ""
    low = s.lower()
    if "youtube.com" in low or "youtu.be" in low:
        u = s.split("?")[0].split("#")[0].rstrip("/")
        m = re.search(r"/channel/([^/?#]+)", u, re.I)
        if m:
            return m.group(1).strip()
        m = re.search(r"/@([^/?#]+)", u, re.I)
        if m:
            return m.group(1).strip()
        m = re.search(r"/c/([^/?#]+)", u, re.I)
        if m:
            return m.group(1).strip()
        m = re.search(r"/user/([^/?#]+)", u, re.I)
        if m:
            return m.group(1).strip()
    return s.lstrip("@").strip()


def youtube_about_page_url(identifier: str) -> str | None:
    if not identifier:
        return None
    if identifier.startswith("UC") and len(identifier) >= 20:
        return f"https://www.youtube.com/channel/{identifier}/about"
    return f"https://www.youtube.com/@{identifier}/about"


def fetch_url_text(url: str, *, timeout: int = 10) -> str:
    req = Request(url, headers={"User-Agent": _USER_AGENT}, method="GET")
    with urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="ignore")


def channel_about_contains_proof(identifier: str, proof_url: str) -> tuple[bool, str | None]:
    """
    尝试抓取频道 about 页 HTML，判断 proof_url（完整字符串）是否出现在页面中。
    返回 (是否包含, 错误说明)；错误说明非空表示未校验成功（网络或 404 等）。
    """
    needle = (proof_url or "").strip()
    if not needle:
        return True, None
    about = youtube_about_page_url(identifier)
    if not about:
        return False, "请填写正确的 YouTube 频道信息。"
    try:
        html = fetch_url_text(about).lower()
    except HTTPError:
        return False, "暂时无法打开频道页面，请稍后再试。"
    except URLError:
        return False, "暂时无法打开频道页面，请稍后再试。"
    except OSError:
        return False, "暂时无法打开频道页面，请稍后再试。"
    n = needle.lower()
    if n in html:
        return True, None
    return False, "并没有在简介里找到要求填写的内容。"

