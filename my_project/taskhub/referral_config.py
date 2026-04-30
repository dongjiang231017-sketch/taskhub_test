from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.db.utils import OperationalError, ProgrammingError

from .models import ReferralRewardConfig


def _as_decimal(value, default: str) -> Decimal:
    if value is None:
        return Decimal(default)
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def get_referral_reward_rate() -> Decimal:
    """后台优先，环境变量兜底。"""

    fallback = _as_decimal(getattr(settings, "INVITE_COMMISSION_RATE", Decimal("0.20")), "0.20")
    try:
        obj = ReferralRewardConfig.objects.order_by("-id").first()
    except (ProgrammingError, OperationalError):
        return fallback
    if obj is None:
        return fallback
    return Decimal(str(obj.direct_invite_rate))


def get_referral_reward_rates() -> dict[str, Decimal]:
    """读取邀请活动全部比例；表未迁移时使用文档默认值兜底。"""

    direct_task_fallback = _as_decimal(getattr(settings, "INVITE_COMMISSION_RATE", Decimal("0.20")), "0.20")
    fallback = {
        "task_direct_rate": direct_task_fallback,
        "task_second_rate": Decimal("0.10"),
        "membership_direct_rate": Decimal("0.20"),
        "membership_second_rate": Decimal("0.10"),
    }
    try:
        obj = ReferralRewardConfig.objects.order_by("-id").first()
    except (ProgrammingError, OperationalError):
        return {
            **fallback,
            # 兼容旧键名：前端若仍读取 recharge，也返回同一组“会员开通返利”比例
            "recharge_direct_rate": fallback["membership_direct_rate"],
            "recharge_second_rate": fallback["membership_second_rate"],
        }
    if obj is None:
        return {
            **fallback,
            "recharge_direct_rate": fallback["membership_direct_rate"],
            "recharge_second_rate": fallback["membership_second_rate"],
        }
    result = {
        "task_direct_rate": Decimal(str(obj.direct_invite_rate)),
        "task_second_rate": Decimal(str(getattr(obj, "second_task_rate", fallback["task_second_rate"]))),
        "membership_direct_rate": Decimal(
            str(getattr(obj, "direct_recharge_rate", fallback["membership_direct_rate"]))
        ),
        "membership_second_rate": Decimal(
            str(getattr(obj, "second_recharge_rate", fallback["membership_second_rate"]))
        ),
    }
    result["recharge_direct_rate"] = result["membership_direct_rate"]
    result["recharge_second_rate"] = result["membership_second_rate"]
    return result
