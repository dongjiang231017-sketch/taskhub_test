"""任务录用后的钱包奖励（与 Task.reward_usdt / reward_th_coin 对应）。"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from django.utils import timezone

from wallets.models import Transaction, Wallet

from .models import TaskApplication

_MONEY_QUANT = Decimal("0.01")


def _to_wallet_decimal(value: Decimal | None) -> Decimal:
    """Wallet / Transaction 为 2 位小数；任务上 reward_usdt 可能为 4 位，避免 MySQL 严格模式写入报错。"""
    if value is None:
        return Decimal("0.00")
    return value.quantize(_MONEY_QUANT, rounding=ROUND_HALF_UP)


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

    out = {"granted": True, "usdt": "0", "th_coin": "0"}

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

    now = timezone.now()
    TaskApplication.objects.filter(pk=application.pk).update(reward_paid_at=now)
    application.reward_paid_at = now

    return out
