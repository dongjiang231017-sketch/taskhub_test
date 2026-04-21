"""
Telegram Bot：接收 getUpdates Webhook，解析私聊 /start <payload>，
写入 TelegramStartInvitePending，供随后 POST /api/v1/auth/telegram/ 消费以绑定 referrer。
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .integration_config import get_telegram_bot_token
from .models import TelegramStartInvitePending

logger = logging.getLogger(__name__)

_RE_START = re.compile(r"^/start(?:@[^\s]+)?(?:\s+(?P<payload>.+))?$", re.UNICODE)


def extract_start_payload_from_message_text(text: str | None) -> str | None:
    if not text or not isinstance(text, str):
        return None
    m = _RE_START.match(text.strip())
    if not m or not m.group("payload"):
        return None
    p = m.group("payload").strip()
    if not p:
        return None
    return p[:64]


def _verify_webhook_secret(request) -> bool:
    secret = (getattr(settings, "TELEGRAM_WEBHOOK_SECRET", None) or "").strip()
    if not secret:
        return True
    got = (request.headers.get("X-Telegram-Bot-Api-Secret-Token") or "").strip()
    return got == secret


def _process_message(msg: dict[str, Any]) -> None:
    chat = msg.get("chat") or {}
    if chat.get("type") != "private":
        return
    from_user = msg.get("from") or {}
    tid = from_user.get("id")
    if tid is None:
        return
    try:
        telegram_id = int(tid)
    except (TypeError, ValueError):
        return
    text = msg.get("text")
    payload = extract_start_payload_from_message_text(text)
    if not payload:
        return
    TelegramStartInvitePending.objects.update_or_create(
        telegram_id=telegram_id,
        defaults={"start_payload": payload},
    )


@csrf_exempt
@require_POST
def telegram_bot_webhook_api(request):
    """
    Telegram Bot API Webhook 入口。
    须在 BotFather / 或调用 setWebhook 指向：https://<你的域名>/api/v1/telegram/webhook/
    """
    if not get_telegram_bot_token():
        return HttpResponse("no bot token", status=503)

    if not _verify_webhook_secret(request):
        return HttpResponse("forbidden", status=403)

    try:
        body = request.body.decode("utf-8") if request.body else ""
        update = json.loads(body) if body else {}
    except (UnicodeDecodeError, json.JSONDecodeError):
        logger.warning("telegram webhook: invalid json")
        return JsonResponse({"ok": True})

    try:
        if "message" in update:
            _process_message(update["message"])
        elif "edited_message" in update:
            _process_message(update["edited_message"])
    except Exception:
        logger.exception("telegram webhook: process update failed")

    return JsonResponse({"ok": True})
