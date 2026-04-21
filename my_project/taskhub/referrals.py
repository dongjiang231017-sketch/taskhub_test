"""邀请 / 推荐人绑定（Telegram start_param、可选 body invite_code）。"""

from __future__ import annotations

from users.models import FrontendUser


def try_bind_referrer_by_invite_code(user: FrontendUser, raw_code: str | None) -> bool:
    """
    若用户尚无 referrer，则按邀请码绑定推荐人。
    raw_code 一般为 Mini App 链接 ?startapp= 传入的 start_param，或注册 body 里的 invite_code。
    成功返回 True；已绑定 / 无效码 / 自己邀请自己 返回 False。
    """
    if not raw_code:
        return False
    code = str(raw_code).strip()[:10]
    if len(code) < 4:
        return False
    if user.referrer_id:
        return False
    ref = (
        FrontendUser.objects.filter(invite_code__iexact=code)
        .exclude(pk=user.pk)
        .first()
    )
    if not ref:
        return False
    user.referrer = ref
    user.save(update_fields=["referrer"])
    return True
