"""Instagram 用户名规范化；简介链接子串匹配供 Apify 校验复用。"""

from __future__ import annotations

import re


def normalize_instagram_username(raw: str | None) -> str:
    """从 @handle、完整 profile URL 等提取 Instagram 用户名（不含 @）。"""
    if not raw:
        return ""
    s = str(raw).strip()
    if not s:
        return ""
    low = s.lower()
    if "instagram.com" in low:
        u = s.split("?")[0].split("#")[0].rstrip("/")
        m = re.search(r"instagram\.com/([^/?#]+)", u, re.I)
        if m:
            seg = m.group(1).strip().lstrip("@")
            if seg.lower() in ("p", "reel", "reels", "stories", "explore", "accounts", "direct"):
                return ""
            return seg
    return s.lstrip("@").strip()


def _proof_needle_variants(needle: str) -> list[str]:
    """
    严格一致：仅保留空白规整与大小写无关比较用的变体（小写）。
    不再互换 http/https，避免与后台配置字符串不一致仍通过。
    """
    n = (needle or "").strip()
    if not n:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for x in (n.lower(), n.rstrip("/").lower()):
        xl = x.strip()
        if xl and xl not in seen:
            seen.add(xl)
            out.append(xl)
    return out


def _strict_url_continuation(haystack_lower: str, j: int) -> bool:
    """
    若从 j 起仍像「同一 URL 未结束」，返回 True（本处匹配应放弃）。
    含：路径段延续（/ 后仍有非 ?# 内容）、用户名/路径尾部粘连（字母数字 _）。
    """
    hlen = len(haystack_lower)
    if j >= hlen:
        return False
    c = haystack_lower[j]
    if c.isalnum() or c == "_":
        return True
    if c == "/":
        k = j + 1
        while k < hlen and haystack_lower[k] == "/":
            k += 1
        if k >= hlen:
            return False
        if haystack_lower[k] in "?#":
            return False
        return True
    return False


def _needle_in_haystack_strict(haystack_lower: str, needle_lower: str) -> bool:
    """
    在合并文本中查找 needle：前后均不得像 URL 粘连；禁止更长的 path/用户名前缀误命中。
    """
    if not needle_lower:
        return False
    nl = len(needle_lower)
    if nl > len(haystack_lower):
        return False
    pos = 0
    while pos <= len(haystack_lower) - nl:
        i = haystack_lower.find(needle_lower, pos)
        if i == -1:
            break
        if i > 0:
            prev = haystack_lower[i - 1]
            if prev.isalnum() or prev == "_":
                pos = i + 1
                continue
        j = i + nl
        if _strict_url_continuation(haystack_lower, j):
            pos = i + 1
            continue
        return True
    return False


def instagram_proof_link_too_generic(proof_url: str) -> bool:
    """拒绝仅主机根路径的 instagram.com 证明链接（否则会匹配资料里任意主页 URL）。"""
    s = (proof_url or "").strip().lower().rstrip("/")
    if not s:
        return True
    roots = (
        "https://instagram.com",
        "https://www.instagram.com",
        "http://instagram.com",
        "http://www.instagram.com",
    )
    return s in roots


def text_contains_proof_link(haystack: str, proof_url: str) -> bool:
    """简介/外链合并文本中须出现与配置严格一致的链接（仅大小写与末尾 / 放宽；scheme 不互换）。"""
    hay = (haystack or "").lower()
    for needle in _proof_needle_variants(proof_url):
        if needle and _needle_in_haystack_strict(hay, needle):
            return True
    return False
