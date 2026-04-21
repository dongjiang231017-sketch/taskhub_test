"""邀请 / 推荐人绑定（Telegram start_param、可选 body invite_code / ref_ 形态）。"""

from __future__ import annotations

from django.conf import settings

from users.models import FrontendUser


def _strip_invite_start_prefix(raw: str) -> str:
    """去掉常见前缀 ref_（与 t.me/bot?start=ref_xxx 一致），再 strip。"""
    s = str(raw).strip()
    prefix = getattr(settings, "TELEGRAM_INVITE_START_PREFIX", "ref_") or "ref_"
    low = s.lower()
    p = prefix.lower()
    if low.startswith(p):
        s = s[len(prefix) :]
    elif low.startswith("ref_"):
        s = s[4:]
    return s.strip()


def resolve_inviter_from_start_token(raw_code: str | None, *, exclude_user_id: int) -> FrontendUser | None:
    """
    将 start_param / body 里的邀请载荷解析为「邀请人」用户。
    支持：ref_<telegram_id>、纯数字 Telegram ID、invite_code（不区分大小写，最长 10 位）。
    """
    if not raw_code:
        return None
    token = _strip_invite_start_prefix(str(raw_code))
    if len(token) < 4:
        return None
    # 纯数字：按 Telegram user id 查找（与 https://t.me/bot?start=ref_6702754957 一类链接一致）
    if token.isdigit() and 5 <= len(token) <= 15:
        ref = FrontendUser.objects.filter(telegram_id=int(token)).exclude(pk=exclude_user_id).first()
        if ref:
            return ref
    # 邀请码
    return (
        FrontendUser.objects.filter(invite_code__iexact=token[:10])
        .exclude(pk=exclude_user_id)
        .first()
    )


def try_bind_referrer_by_invite_code(user: FrontendUser, raw_code: str | None) -> bool:
    """
    若用户尚无 referrer，则按 start_param / invite_code / ref_<tg_id> 绑定推荐人。
    成功返回 True；已绑定 / 无效 / 自己邀请自己 返回 False。
    """
    if not raw_code or user.referrer_id:
        return False
    ref = resolve_inviter_from_start_token(raw_code, exclude_user_id=user.pk)
    if not ref:
        return False
    user.referrer = ref
    user.save(update_fields=["referrer"])
    return True
