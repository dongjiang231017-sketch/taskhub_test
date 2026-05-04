"""Telegram Bot API：校验用户是否在群内（getChatMember）。"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request


def normalize_telegram_chat_id(raw: str | int | None) -> str | None:
    """支持超级群 -100…、普通群数字 id、@username、或公开 t.me 频道/群链接。"""
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None

    if re.fullmatch(r"-?\d+", s):
        return s

    if s.startswith("@"):
        username = s.lstrip("@").strip()
        return f"@{username}" if username else None

    candidate = s
    if "://" not in candidate and (
        candidate.lower().startswith("t.me/") or candidate.lower().startswith("telegram.me/")
    ):
        candidate = f"https://{candidate}"

    if "://" in candidate:
        parsed = urllib.parse.urlparse(candidate)
        host = (parsed.netloc or "").lower()
        path_parts = [part for part in (parsed.path or "").split("/") if part]
        if host in {"t.me", "www.t.me", "telegram.me", "www.telegram.me"} and path_parts:
            # 公开预览页常见 /s/<username>
            if path_parts[0] == "s" and len(path_parts) >= 2:
                username = path_parts[1]
            else:
                username = path_parts[0]
            username = username.strip().lstrip("@")
            # 私有邀请链接（+xxxx / joinchat/xxxx）不能作为 getChatMember 的 chat_id
            if not username or username.startswith("+") or username == "joinchat":
                return None
            return f"@{username}"

    if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{3,}", s):
        return f"@{s}"
    return None


def extract_telegram_chat_id_from_config(config: dict | None) -> str | None:
    """
    从任务交互配置里提取可供 getChatMember 使用的 chat_id：
    - 优先 telegram_chat_id / telegram_group_id
    - 兼容 telegram_chat_username / telegram_channel_username
    - 若未显式填写，可回退解析公开 invite_link
    """
    cfg = config or {}
    for key in (
        "telegram_chat_id",
        "telegram_group_id",
        "telegram_chat_username",
        "telegram_channel_username",
        "telegram_chat",
        "telegram_channel",
    ):
        chat_id = normalize_telegram_chat_id(cfg.get(key))
        if chat_id:
            return chat_id
    for key in ("telegram_invite_link", "invite_link"):
        chat_id = normalize_telegram_chat_id(cfg.get(key))
        if chat_id:
            return chat_id
    return None


def _telegram_api_get(token: str, method: str, params: dict[str, str]) -> dict:
    q = urllib.parse.urlencode(params)
    url = f"https://api.telegram.org/bot{token}/{method}?{q}"
    req = urllib.request.Request(url, method="GET", headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read().decode("utf-8", errors="replace"))
        except json.JSONDecodeError:
            body = {}
        desc = ""
        if isinstance(body.get("description"), str):
            desc = body["description"]
        return {"ok": False, "description": desc or f"HTTP {e.code}"}
    except (urllib.error.URLError, OSError, json.JSONDecodeError):
        return {"ok": False, "description": "network_error"}


def user_is_member_of_chat(bot_token: str, chat_id: str, telegram_user_id: int) -> tuple[bool, str | None]:
    """
    调用 getChatMember；成功且在群内返回 (True, None)。
    失败返回 (False, 面向用户的简短说明)。
    """
    cid = normalize_telegram_chat_id(chat_id)
    if not cid or not bot_token.strip():
        return False, "任务配置不完整，请联系发布方。"
    if not telegram_user_id:
        return False, "请先使用 Telegram 登录本应用，以便校验您是否已入群。"
    data = _telegram_api_get(
        bot_token.strip(),
        "getChatMember",
        {"chat_id": cid, "user_id": str(int(telegram_user_id))},
    )
    if not data.get("ok"):
        desc = (data.get("description") or "").lower()
        if "user not found" in desc or "participant" in desc and "not" in desc:
            return False, "未检测到您已加入该群组，请先入群后再试。"
        if "bot is not a member" in desc or "bot was kicked" in desc:
            return False, "校验机器人未加入目标群组/频道，请联系发布方检查机器人配置。"
        if "have no rights" in desc or "not enough rights" in desc or "member list is inaccessible" in desc:
            return False, "校验机器人缺少查看成员权限；频道通常需要把机器人设为管理员。"
        if "chat not found" in desc:
            return False, "目标群组/频道标识无效，请联系发布方检查 telegram_chat_id 是否填写为 @用户名 或 -100… 数字 ID。"
        if "not a member" in desc:
            return False, "未检测到您已加入该群组，请先入群后再试。"
        return False, "暂时无法完成校验，请稍后再试。"
    member = data.get("result") or {}
    status = (member.get("status") or "").lower()
    if status in ("creator", "administrator", "member"):
        return True, None
    if status == "restricted":
        if member.get("is_member") is True:
            return True, None
        return False, "未检测到您已加入该群组，请先入群后再试。"
    if status in ("left", "kicked"):
        return False, "未检测到您已加入该群组，请先入群后再试。"
    return False, "未检测到您已加入该群组，请先入群后再试。"
