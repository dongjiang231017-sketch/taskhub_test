from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.db.utils import OperationalError, ProgrammingError

from .models import ReferralRewardConfig


def get_referral_reward_rate() -> Decimal:
    """后台优先，环境变量兜底。"""

    fallback = getattr(settings, "INVITE_COMMISSION_RATE", Decimal("0.10"))
    if not isinstance(fallback, Decimal):
        fallback = Decimal(str(fallback))
    try:
        obj = ReferralRewardConfig.objects.first()
    except (ProgrammingError, OperationalError):
        return fallback
    if obj is None:
        return fallback
    return Decimal(str(obj.direct_invite_rate))
