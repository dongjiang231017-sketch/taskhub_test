"""邀请活动返佣发放工具。"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from django.db import transaction

from wallets.models import Transaction, Wallet

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


def grant_recharge_referral_rewards(source: Transaction) -> list[dict]:
    """
    充值流水创建后触发二级充值分佣。
    仅处理 Transaction.change_type=recharge 且 USDT 正向入账，后台 admin_adjust 不会触发。
    """

    if source.change_type != "recharge" or source.asset != Transaction.ASSET_USDT or source.amount <= 0:
        return []

    user = source.wallet.user
    rates = get_referral_reward_rates()
    parent = getattr(user, "referrer", None)
    grandparent = getattr(parent, "referrer", None) if parent is not None else None
    seen_user_ids = {user.id}
    chain = (
        (1, parent, rates["recharge_direct_rate"], f"一级充值佣金：{user.username} 充值 {source.amount} USDT"),
        (2, grandparent, rates["recharge_second_rate"], f"二级充值佣金：{user.username} 充值 {source.amount} USDT"),
    )

    granted: list[dict] = []
    with transaction.atomic():
        for level, referrer, rate, remark in chain:
            if referrer is None or referrer.id in seen_user_ids or rate <= 0:
                continue
            reward = (source.amount * rate).quantize(_MONEY_QUANT, rounding=ROUND_HALF_UP)
            if reward <= 0:
                continue
            _credit_reward(referrer, reward, remark=remark)
            seen_user_ids.add(referrer.id)
            granted.append(
                {
                    "level": level,
                    "user_id": referrer.id,
                    "amount": str(reward),
                    "rate": str(rate),
                    "source_transaction_id": source.id,
                }
            )
    return granted
