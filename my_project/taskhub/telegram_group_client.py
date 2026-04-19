"""Telegram Bot API：校验用户是否在群内（getChatMember）。"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request


def normalize_telegram_chat_id(raw: str | int | None) -> str | None:
    """支持超级群 -100…、普通群数字 id、或 @username 频道/群公开链接名。"""
    if raw is None:
        return None
    s = str(raw).strip()
    return s or None


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
        if "not a member" in desc or "chat not found" in desc or "bot was kicked" in desc:
            return False, "暂时无法校验入群状态，请稍后再试或联系客服。"
        if "bot is not a member" in desc or "have no rights" in desc or "not enough rights" in desc:
            return False, "校验服务暂不可用，请联系发布方。"
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
