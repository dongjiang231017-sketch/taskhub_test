"""邀请活动返佣发放工具。"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from django.db import transaction

from users.models import FrontendUser
from wallets.models import Transaction, Wallet

from .models import MembershipLevelConfig
from .referral_config import get_referral_reward_rates

_MONEY_QUANT = Decimal("0.01")


def _credit_reward(referrer, amount: Decimal, *, remark: str) -> None:
    Wallet.objects.get_or_create(user=referrer)
    wallet = Wallet.objects.select_for_update().get(user=referrer)
    old_balance = wallet.balance
    new_balance = (old_balance + amount).quantize(_MONEY_QUANT, rounding=ROUND_HALF_UP)
    Transaction.objects.create(
        wallet=wallet,
        asset=Transaction.ASSET_USDT,
        amount=amount,
        before_balance=old_balance,
        after_balance=new_balance,
        change_type="reward",
        remark=remark[:250],
    )
    wallet.balance = new_balance
    wallet.save(create_transaction=False)


def _membership_reward_cap_amount(user: FrontendUser | None) -> Decimal:
    if user is None:
        return Decimal("0.00")
    try:
        level = int(getattr(user, "membership_level", 0) or 0)
    except (TypeError, ValueError):
        level = 0
    if level <= 0:
        return Decimal("0.00")
    cfg = MembershipLevelConfig.for_level(level)
    if cfg is None:
        return Decimal("0.00")
    return Decimal(str(cfg.join_fee_usdt)).quantize(_MONEY_QUANT, rounding=ROUND_HALF_UP)


def _burned_reward_amount(*, purchase_amount: Decimal, rate: Decimal, referrer: FrontendUser | None) -> tuple[Decimal, Decimal]:
    cap_amount = _membership_reward_cap_amount(referrer)
    if cap_amount <= Decimal("0.00") or rate <= Decimal("0"):
        return Decimal("0.00"), cap_amount
    reward_base = min(
        purchase_amount.quantize(_MONEY_QUANT, rounding=ROUND_HALF_UP),
        cap_amount,
    )
    if reward_base <= Decimal("0.00"):
        return Decimal("0.00"), cap_amount
    reward = (reward_base * rate).quantize(_MONEY_QUANT, rounding=ROUND_HALF_UP)
    return reward, cap_amount


def grant_membership_purchase_referral_rewards(
    *,
    purchaser: FrontendUser,
    purchased_level: MembershipLevelConfig,
    purchase_amount: Decimal,
    source_transaction: Transaction | None = None,
) -> list[dict]:
    """
    会员购买后触发二级返利。

    返利比例取后台 ReferralRewardConfig，返利基数为：
    min(购买金额, 上级当前会员等级的 join_fee_usdt)。
    若上级是 VIP0 / 未配置等级，则该层返利为 0（烧伤）。
    """

    purchase_amount = Decimal(str(purchase_amount)).quantize(_MONEY_QUANT, rounding=ROUND_HALF_UP)
    if purchase_amount <= Decimal("0.00"):
        return []

    rates = get_referral_reward_rates()
    parent = getattr(purchaser, "referrer", None)
    grandparent = getattr(parent, "referrer", None) if parent is not None else None
    seen_user_ids = {purchaser.id}
    chain = (
        (
            1,
            parent,
            rates["membership_direct_rate"],
            "一级会员开通返利",
        ),
        (
            2,
            grandparent,
            rates["membership_second_rate"],
            "二级会员开通返利",
        ),
    )

    granted: list[dict] = []
    with transaction.atomic():
        for level, referrer, rate, reward_label in chain:
            if referrer is None or referrer.id in seen_user_ids or rate <= 0:
                continue
            reward, cap_amount = _burned_reward_amount(
                purchase_amount=purchase_amount,
                rate=rate,
                referrer=referrer,
            )
            if reward <= 0:
                continue
            reward_base = min(purchase_amount, cap_amount).quantize(_MONEY_QUANT, rounding=ROUND_HALF_UP)
            burned = reward_base < purchase_amount
            if burned:
                remark = (
                    f"{reward_label}（烧伤封顶 {reward_base} USDT）："
                    f"{purchaser.username} 开通 {purchased_level.name} {purchase_amount} USDT"
                )
            else:
                remark = f"{reward_label}：{purchaser.username} 开通 {purchased_level.name} {purchase_amount} USDT"
            _credit_reward(referrer, reward, remark=remark[:250])
            seen_user_ids.add(referrer.id)
            granted.append(
                {
                    "level": level,
                    "user_id": referrer.id,
                    "amount": str(reward),
                    "rate": str(rate),
                    "purchase_amount": str(purchase_amount),
                    "reward_base_amount": str(reward_base),
                    "cap_amount": str(cap_amount),
                    "burned": burned,
                    "source_transaction_id": source_transaction.id if source_transaction is not None else None,
                }
            )
    return granted


def grant_recharge_referral_rewards(source: Transaction) -> list[dict]:
    """
    兼容旧入口：充值返利逻辑已下线，改由会员开通返利触发。
    """
    return []
