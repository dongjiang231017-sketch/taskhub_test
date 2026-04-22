"""Telegram Web App / Mini App：校验 initData（官方 HMAC 算法）。"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any
from urllib.parse import parse_qsl, unquote


def parse_telegram_user_from_init_data(parsed: dict[str, str]) -> dict[str, Any] | None:
    raw = parsed.get("user")
    if not raw:
        return None
    s = str(raw).strip()
    data: dict[str, Any] | None = None
    for payload in (s, unquote(s)):
        try:
            obj = json.loads(payload)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            data = obj
            break
    if not data:
        return None
    # 部分客户端/中间层可能传 camelCase，与 Bot API 的 snake_case 对齐
    if "first_name" not in data and data.get("firstName") is not None:
        data["first_name"] = data.get("firstName")
    if "last_name" not in data and data.get("lastName") is not None:
        data["last_name"] = data.get("lastName")
    if "username" not in data and data.get("Username"):
        data["username"] = data.get("Username")
    return data


def validate_webapp_init_data(init_data: str, bot_token: str, *, max_age_seconds: int = 86400) -> dict[str, Any]:
    """
    校验 Mini App 传入的 initData 字符串（WebApp 的 window.Telegram.WebApp.initData）。
    成功返回 dict，含 telegram_user（原始 user 对象）、auth_date、parsed_pairs。
    失败抛 ValueError。
    """
    if not bot_token:
        raise ValueError("未配置 TELEGRAM_BOT_TOKEN")
    if not (init_data or "").strip():
        raise ValueError("init_data 不能为空")

    pairs = dict(parse_qsl(init_data.strip(), keep_blank_values=True))
    received_hash = pairs.pop("hash", None)
    if not received_hash:
        raise ValueError("init_data 缺少 hash")

    auth_date_raw = pairs.get("auth_date")
    if auth_date_raw:
        try:
            auth_date = int(auth_date_raw)
        except ValueError as exc:
            raise ValueError("auth_date 无效") from exc
        if max_age_seconds > 0 and int(time.time()) - auth_date > max_age_seconds:
            raise ValueError("init_data 已过期，请重新打开 Mini App")

    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret_key = hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()
    computed = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(computed, received_hash):
        raise ValueError("init_data 签名校验失败")

    tg_user = parse_telegram_user_from_init_data(pairs)
    if not tg_user or "id" not in tg_user:
        raise ValueError("init_data 中缺少 user 或 user.id")

    return {
        "telegram_user": tg_user,
        "auth_date": int(auth_date_raw) if auth_date_raw else None,
        "parsed_pairs": pairs,
    }
