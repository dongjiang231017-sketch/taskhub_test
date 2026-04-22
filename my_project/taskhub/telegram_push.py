"""Telegram Bot 私聊推送：欢迎消息、任务完成、签到成功等。"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from decimal import Decimal, InvalidOperation
from typing import Any

from django.conf import settings

from users.models import FrontendUser

from .integration_config import get_telegram_bot_token

logger = logging.getLogger(__name__)


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _to_decimal(value: Any) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")


def _fmt_amount(value: Any) -> str:
    dec = _to_decimal(value)
    text = format(dec, "f")
    text = text.rstrip("0").rstrip(".")
    return text or "0"


def _telegram_api_post(method: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    token = get_telegram_bot_token()
    if not token:
        return None
    api = f"https://api.telegram.org/bot{token}/{method}"
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        api,
        data=data,
        method="POST",
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json; charset=utf-8",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode("utf-8") if resp else ""
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        logger.warning("telegram push %s failed: %s %s", method, exc.code, body)
        return None
    except urllib.error.URLError as exc:
        logger.warning("telegram push %s failed: %s", method, exc)
        return None

    try:
        parsed = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        logger.warning("telegram push %s returned invalid json: %r", method, raw[:500])
        return None

    if not parsed.get("ok", False):
        logger.warning("telegram push %s not ok: %s", method, parsed)
        return None
    return parsed


def _bot_mini_app_url() -> str:
    direct = _clean_text(getattr(settings, "TELEGRAM_MINI_APP_URL", ""))
    if direct:
        return direct
    bot = _clean_text(getattr(settings, "TELEGRAM_BOT_USERNAME", "")).lstrip("@")
    short = _clean_text(getattr(settings, "TELEGRAM_MINI_APP_SHORT_NAME", ""))
    if bot and short:
        return f"https://t.me/{bot}/{short}"
    return ""


def _announcement_url() -> str:
    return _clean_text(getattr(settings, "TELEGRAM_ANNOUNCEMENT_URL", ""))


def _community_url() -> str:
    return _clean_text(getattr(settings, "TELEGRAM_COMMUNITY_URL", ""))


def _welcome_image_url() -> str:
    return _clean_text(getattr(settings, "TELEGRAM_BOT_WELCOME_IMAGE_URL", ""))


def _welcome_text(display_name: str) -> str:
    custom = _clean_text(getattr(settings, "TELEGRAM_BOT_WELCOME_TEXT", ""))
    if custom:
        return custom.replace("{name}", display_name)
    return (
        "🎉 欢迎加入 TaskHub\n\n"
        f"你好，{display_name}！\n\n"
        "💰 完成社交媒体任务赚取 USDT\n"
        "📅 每日签到领取 TH Coin\n"
        "👥 邀请好友赚返佣，持续放大收益\n\n"
        "👇 点击下方按钮，立即开始做任务。"
    )


def _inline_keyboard(rows: list[list[tuple[str, str]]]) -> dict[str, Any] | None:
    inline_rows: list[list[dict[str, str]]] = []
    for row in rows:
        btns = []
        for text, url in row:
            if not _clean_text(text) or not _clean_text(url):
                continue
            btns.append({"text": text, "url": url})
        if btns:
            inline_rows.append(btns)
    if not inline_rows:
        return None
    return {"inline_keyboard": inline_rows}


def _welcome_keyboard() -> dict[str, Any] | None:
    app_url = _bot_mini_app_url()
    announce_url = _announcement_url()
    community_url = _community_url()
    rows: list[list[tuple[str, str]]] = []
    first_row: list[tuple[str, str]] = []
    if app_url:
        first_row.append(("🚀 打开任务中心", app_url))
    if announce_url:
        first_row.append(("📣 公告频道", announce_url))
    if first_row:
        rows.append(first_row[:2])
    second_row: list[tuple[str, str]] = []
    if community_url:
        second_row.append(("👥 社区互助群", community_url))
    if app_url:
        second_row.append(("📋 查看任务列表", app_url))
    if second_row:
        rows.append(second_row[:2])
    return _inline_keyboard(rows)


def _task_cta_keyboard() -> dict[str, Any] | None:
    app_url = _bot_mini_app_url()
    community_url = _community_url()
    rows: list[list[tuple[str, str]]] = []
    row: list[tuple[str, str]] = []
    if app_url:
        row.append(("📋 查看更多任务", app_url))
    if community_url:
        row.append(("👥 社区互助群", community_url))
    if row:
        rows.append(row[:2])
    return _inline_keyboard(rows)


def send_bot_message(chat_id: int | str, text: str, *, reply_markup: dict[str, Any] | None = None) -> None:
    payload: dict[str, Any] = {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": True,
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    _telegram_api_post("sendMessage", payload)


def send_bot_photo(
    chat_id: int | str,
    photo_url: str,
    *,
    caption: str = "",
    reply_markup: dict[str, Any] | None = None,
) -> None:
    if not _clean_text(photo_url):
        return
    payload: dict[str, Any] = {
        "chat_id": chat_id,
        "photo": photo_url,
    }
    if caption:
        payload["caption"] = caption
    if reply_markup:
        payload["reply_markup"] = reply_markup
    _telegram_api_post("sendPhoto", payload)


def send_welcome_message(chat_id: int | str, *, first_name: str | None = None) -> None:
    name = _clean_text(first_name) or "朋友"
    keyboard = _welcome_keyboard()
    image_url = _welcome_image_url()
    if image_url:
        send_bot_photo(chat_id, image_url)
    send_bot_message(chat_id, _welcome_text(name), reply_markup=keyboard)


def _user_chat_id(user: FrontendUser) -> int | None:
    tg = getattr(user, "telegram_id", None)
    if tg is None:
        return None
    try:
        return int(tg)
    except (TypeError, ValueError):
        return None


def send_task_completion_message(application, granted: dict[str, Any] | None) -> None:
    user = getattr(application, "applicant", None)
    if user is None:
        return
    chat_id = _user_chat_id(user)
    if chat_id is None:
        return

    reason = _clean_text((granted or {}).get("reason"))
    if reason in {"db_error", "already_paid"}:
        return

    lines = ["🎉 任务完成！", "", f"✅ 任务：{application.task.title}"]
    usdt = _to_decimal((granted or {}).get("usdt", "0"))
    th_coin = _to_decimal((granted or {}).get("th_coin", "0"))
    if usdt > 0:
        lines.append(f"💵 奖励：+{_fmt_amount(usdt)} USDT")
    if th_coin > 0:
        lines.append(f"🪙 TH Coin：+{_fmt_amount(th_coin)}")
    if usdt <= 0 and th_coin <= 0:
        lines.append("📌 状态：已完成")
    lines.extend(["", "继续完成更多任务赚取奖励吧！"])
    send_bot_message(chat_id, "\n".join(lines), reply_markup=_task_cta_keyboard())


def send_checkin_success_message(
    user: FrontendUser,
    *,
    streak_days: int,
    granted: dict[str, Any] | None,
    is_makeup: bool = False,
    spent_th_coin: Any = None,
) -> None:
    chat_id = _user_chat_id(user)
    if chat_id is None:
        return

    title = "📅 补签成功！" if is_makeup else "📅 签到成功！"
    lines = [title, "", f"🔥 连续签到：{max(0, int(streak_days or 0))} 天"]
    spent = _to_decimal(spent_th_coin)
    if is_makeup and spent > 0:
        lines.append(f"💸 补签消耗：-{_fmt_amount(spent)} TH Coin")
    usdt = _to_decimal((granted or {}).get("usdt", "0"))
    th_coin = _to_decimal((granted or {}).get("th_coin", "0"))
    if usdt > 0:
        lines.append(f"💵 获得奖励：+{_fmt_amount(usdt)} USDT")
    if th_coin > 0:
        lines.append(f"🪙 获得奖励：+{_fmt_amount(th_coin)} TH Coin")
    tail = "明天继续签到可获得更多奖励！" if not is_makeup else "继续保持签到节奏，奖励会越来越高！"
    lines.extend(["", tail])
    send_bot_message(chat_id, "\n".join(lines), reply_markup=_task_cta_keyboard())


def send_daily_task_claim_message(user: FrontendUser, definition, granted: dict[str, Any] | None) -> None:
    chat_id = _user_chat_id(user)
    if chat_id is None:
        return

    lines = ["🎯 每日任务奖励已到账！", "", f"✅ 任务：{definition.title}"]
    usdt = _to_decimal((granted or {}).get("usdt", "0"))
    th_coin = _to_decimal((granted or {}).get("th_coin", "0"))
    if usdt > 0:
        lines.append(f"💵 奖励：+{_fmt_amount(usdt)} USDT")
    if th_coin > 0:
        lines.append(f"🪙 TH Coin：+{_fmt_amount(th_coin)}")
    lines.extend(["", "继续完成更多每日目标吧！"])
    send_bot_message(chat_id, "\n".join(lines), reply_markup=_task_cta_keyboard())


def send_invite_achievement_claim_message(
    user: FrontendUser,
    tier,
    granted: dict[str, Any] | None,
    *,
    invited_total: int,
) -> None:
    chat_id = _user_chat_id(user)
    if chat_id is None:
        return

    lines = [
        "🏆 邀请成就奖励已到账！",
        "",
        f"✅ 成就：{tier.title}",
        f"👥 有效邀请：{max(0, int(invited_total or 0))} 人",
    ]
    usdt = _to_decimal((granted or {}).get("usdt", "0"))
    th_coin = _to_decimal((granted or {}).get("th_coin", "0"))
    if usdt > 0:
        lines.append(f"💵 奖励：+{_fmt_amount(usdt)} USDT")
    if th_coin > 0:
        lines.append(f"🪙 TH Coin：+{_fmt_amount(th_coin)}")
    lines.extend(["", "继续邀请好友，解锁更高阶奖励！"])
    send_bot_message(chat_id, "\n".join(lines), reply_markup=_task_cta_keyboard())
