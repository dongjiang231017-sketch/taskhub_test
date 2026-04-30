"""任务录用后的钱包奖励（与 Task.reward_usdt / reward_th_coin 对应）。"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from django.utils import timezone

from wallets.models import Transaction, Wallet

from .models import TaskApplication
from .referral_config import get_referral_reward_rates

_MONEY_QUANT = Decimal("0.01")


def _to_wallet_decimal(value: Decimal | None) -> Decimal:
    """Wallet / Transaction 为 2 位小数；任务上 reward_usdt 可能为 4 位，避免 MySQL 严格模式写入报错。"""
    if value is None:
        return Decimal("0.00")
    return value.quantize(_MONEY_QUANT, rounding=ROUND_HALF_UP)


def _credit_referral_wallet(referrer, reward: Decimal, *, asset: str, remark: str) -> None:
    Wallet.objects.get_or_create(user=referrer)
    wallet = Wallet.objects.select_for_update().get(user=referrer)
    if asset == Transaction.ASSET_TH_COIN:
        old_balance = wallet.frozen
        new_balance = (old_balance + reward).quantize(_MONEY_QUANT, rounding=ROUND_HALF_UP)
    else:
        old_balance = wallet.balance
        new_balance = (old_balance + reward).quantize(_MONEY_QUANT, rounding=ROUND_HALF_UP)

    Transaction.objects.create(
        wallet=wallet,
        asset=asset,
        amount=reward,
        before_balance=old_balance,
        after_balance=new_balance,
        change_type="reward",
        remark=remark[:250],
    )
    if asset == Transaction.ASSET_TH_COIN:
        wallet.frozen = new_balance
    else:
        wallet.balance = new_balance
    wallet.save(create_transaction=False)


def _grant_referrer_rewards(
    application: TaskApplication,
    task_reward_usdt: Decimal,
    task_reward_th_coin: Decimal,
) -> list[dict]:
    """
    下级完成任务后，一级 / 二级上级按后台配置比例拿推荐奖励。
    奖励按原始资产返佣：USDT 返 USDT，TH Coin 返 TH Coin。
    """

    user = application.applicant
    if task_reward_usdt <= 0 and task_reward_th_coin <= 0:
        return []

    rates = get_referral_reward_rates()
    parent = getattr(user, "referrer", None)
    grandparent = getattr(parent, "referrer", None) if parent is not None else None
    reward_sources = (
        (Transaction.ASSET_USDT, task_reward_usdt, "USDT"),
        (Transaction.ASSET_TH_COIN, task_reward_th_coin, "TH Coin"),
    )
    chain = (
        (1, parent, rates["task_direct_rate"]),
        (2, grandparent, rates["task_second_rate"]),
    )

    granted: list[dict] = []
    for asset, task_reward, asset_label in reward_sources:
        if task_reward <= 0:
            continue
        for level, referrer, rate in chain:
            if referrer is None or rate <= 0:
                continue
            reward = (task_reward * rate).quantize(_MONEY_QUANT, rounding=ROUND_HALF_UP)
            if reward <= 0:
                continue
            remark = f"{'一级' if level == 1 else '二级'}推荐奖励：{user.username} 完成任务 {application.task.title}（{asset_label}）"
            _credit_referral_wallet(referrer, reward, asset=asset, remark=remark)
            granted.append(
                {
                    "level": level,
                    "user_id": referrer.id,
                    "amount": str(reward),
                    "rate": str(rate),
                    "asset": asset,
                    "asset_label": asset_label,
                }
            )
    return granted


def grant_task_completion_reward(application: TaskApplication) -> dict:
    """
    按任务配置的展示奖励入账：USDT -> wallet.balance，TH -> wallet.frozen（与签到一致）。
    同一报名仅发放一次（reward_paid_at）。
    """
    if application.reward_paid_at:
        return {"granted": False, "usdt": "0", "th_coin": "0", "reason": "already_paid"}

    task = application.task
    ru = _to_wallet_decimal(task.reward_usdt if task.reward_usdt is not None else None)
    rt = _to_wallet_decimal(task.reward_th_coin if task.reward_th_coin is not None else None)
    if ru <= 0 and rt <= 0:
        return {"granted": False, "usdt": "0", "th_coin": "0", "reason": "no_reward_configured"}

    user = application.applicant
    Wallet.objects.get_or_create(user=user)
    wallet = Wallet.objects.select_for_update().get(user=user)

    old_b, old_f = wallet.balance, wallet.frozen
    new_b = (old_b + max(ru, Decimal("0"))).quantize(_MONEY_QUANT, rounding=ROUND_HALF_UP)
    new_f = (old_f + max(rt, Decimal("0"))).quantize(_MONEY_QUANT, rounding=ROUND_HALF_UP)

    out = {
        "granted": True,
        "usdt": "0",
        "th_coin": "0",
        "referrer_reward_usdt": "0",
        "referrer_reward_th_coin": "0",
        "referrer_rewards": [],
    }

    if ru > 0:
        Transaction.objects.create(
            wallet=wallet,
            asset=Transaction.ASSET_USDT,
            amount=ru,
            before_balance=old_b,
            after_balance=new_b,
            change_type="task_reward",
            remark=f"任务奖励 USDT：{task.title}"[:250],
        )
        out["usdt"] = str(ru)
    if rt > 0:
        Transaction.objects.create(
            wallet=wallet,
            asset=Transaction.ASSET_TH_COIN,
            amount=rt,
            before_balance=old_f,
            after_balance=new_f,
            change_type="task_reward",
            remark=f"任务奖励 TH Coin：{task.title}"[:250],
        )
        out["th_coin"] = str(rt)

    wallet.balance = new_b
    wallet.frozen = new_f
    wallet.save(create_transaction=False)

    referrer_rewards = _grant_referrer_rewards(application, ru, rt)
    if referrer_rewards:
        total_referrer_reward_usdt = sum(
            (
                Decimal(item["amount"])
                for item in referrer_rewards
                if item.get("asset") == Transaction.ASSET_USDT
            ),
            Decimal("0.00"),
        )
        total_referrer_reward_th = sum(
            (
                Decimal(item["amount"])
                for item in referrer_rewards
                if item.get("asset") == Transaction.ASSET_TH_COIN
            ),
            Decimal("0.00"),
        )
        out["referrer_reward_usdt"] = str(
            total_referrer_reward_usdt.quantize(_MONEY_QUANT, rounding=ROUND_HALF_UP)
        )
        out["referrer_reward_th_coin"] = str(
            total_referrer_reward_th.quantize(_MONEY_QUANT, rounding=ROUND_HALF_UP)
        )
        out["referrer_rewards"] = referrer_rewards

    now = timezone.now()
    TaskApplication.objects.filter(pk=application.pk).update(reward_paid_at=now)
    application.reward_paid_at = now

    return out
