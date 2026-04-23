"""邀请成就：阶梯配置、进度统计、领取发奖。"""

from __future__ import annotations

from decimal import Decimal

from django.db import transaction
from django.db.models import Sum

from users.models import FrontendUser
from wallets.models import Transaction, Wallet

from .models import InviteAchievementClaim, InviteAchievementTier
from .telegram_push import _bot_dynamic_title, send_invite_achievement_claim_message


def count_direct_invites(user: FrontendUser) -> int:
    """与邀请榜一致：直邀且下级账号启用。"""
    return int(user.children.filter(status=True).count())


def _tier_status(invited: int, claimed: bool, threshold: int) -> str:
    if claimed:
        return "claimed"
    if invited >= threshold:
        return "claimable"
    return "locked"


def _invite_achievement_earned_totals(user: FrontendUser) -> tuple[Decimal, Decimal]:
    """
    从钱包账变汇总「邀请成就」已入账奖励（与发奖时 remark 规则一致）。
    返回 (USDT 合计, TH 类合计)；TH 用于前端成就概览「已获 FG」等展示。
    """
    wallet = getattr(user, "wallet", None)
    if wallet is None:
        return Decimal("0"), Decimal("0")
    base = Transaction.objects.filter(wallet=wallet, change_type="invite_achievement", amount__gt=0)
    usdt_raw = base.exclude(remark__icontains="TH Coin").aggregate(s=Sum("amount"))["s"]
    th_raw = base.filter(remark__icontains="TH Coin").aggregate(s=Sum("amount"))["s"]
    usdt = Decimal(usdt_raw or "0")
    th = Decimal(th_raw or "0")
    return usdt, th


def build_invite_achievement_overview(user: FrontendUser) -> dict:
    """成就概览：已完成档数 / 启用档总数、已获 USDT、已获 FG（FG=邀请成就 TH 入账合计）。"""
    tier_ids = list(
        InviteAchievementTier.objects.filter(is_active=True).values_list("id", flat=True)
    )
    total = len(tier_ids)
    if total:
        completed = InviteAchievementClaim.objects.filter(user=user, tier_id__in=tier_ids).count()
    else:
        completed = 0
    usdt, th = _invite_achievement_earned_totals(user)
    return {
        "completed_count": completed,
        "total_count": total,
        "earned_usdt": str(usdt.quantize(Decimal("0.0001"))),
        "earned_fg": str(th.quantize(Decimal("0.01"))),
    }


def build_invite_achievements_payload(user: FrontendUser) -> dict:
    invited = count_direct_invites(user)
    tier_list = list(
        InviteAchievementTier.objects.filter(is_active=True).order_by("sort_order", "invite_threshold", "id")
    )
    active_ids = {t.id for t in tier_list}
    claimed_ids = set(
        InviteAchievementClaim.objects.filter(user=user).values_list("tier_id", flat=True)
    )
    usdt, th = _invite_achievement_earned_totals(user)
    overview = {
        "completed_count": len(active_ids & claimed_ids),
        "total_count": len(active_ids),
        "earned_usdt": str(usdt.quantize(Decimal("0.0001"))),
        "earned_fg": str(th.quantize(Decimal("0.01"))),
    }
    tiers = []
    for t in tier_list:
        claimed = t.id in claimed_ids
        tiers.append(
            {
                "id": t.id,
                "sort_order": t.sort_order,
                "title": _bot_dynamic_title(t.title, getattr(user, "preferred_language", None)),
                "invite_threshold": t.invite_threshold,
                "reward_usdt": str(t.reward_usdt),
                "reward_th": str(t.reward_th),
                "status": _tier_status(invited, claimed, t.invite_threshold),
                "progress_current": invited,
                "progress_target": t.invite_threshold,
            }
        )
    return {
        "invited_total": invited,
        "overview": overview,
        "tiers": tiers,
    }


def grant_invite_achievement_rewards(wallet: Wallet, tier: InviteAchievementTier) -> dict:
    """发放单档奖励；与签到相同走 Transaction + save(create_transaction=False)。"""
    granted = {"usdt": "0", "th_coin": "0"}
    ru, rt = tier.reward_usdt, tier.reward_th
    if ru <= Decimal("0") and rt <= Decimal("0"):
        return granted

    old_b, old_f = wallet.balance, wallet.frozen
    new_b = old_b + max(ru, Decimal("0"))
    new_f = old_f + max(rt, Decimal("0"))
    remark_base = f"邀请成就：{tier.title}（≥{tier.invite_threshold}人）"
    if ru > 0:
        Transaction.objects.create(
            wallet=wallet,
            amount=ru,
            before_balance=old_b,
            after_balance=new_b,
            change_type="invite_achievement",
            remark=f"{remark_base}·USDT",
        )
    if rt > 0:
        Transaction.objects.create(
            wallet=wallet,
            amount=rt,
            before_balance=old_f,
            after_balance=new_f,
            change_type="invite_achievement",
            remark=f"{remark_base}·TH Coin",
        )
    wallet.balance = new_b
    wallet.frozen = new_f
    wallet.save(create_transaction=False)
    if ru > 0:
        granted["usdt"] = str(ru)
    if rt > 0:
        granted["th_coin"] = str(rt)
    return granted


def claim_invite_achievement_tier(
    user: FrontendUser, tier_id: int
) -> tuple[dict | None, str | None, int, int]:
    """
    领取一档邀请成就。
    成功: (payload, None, 200, 0)
    失败: (None, message, http_status, api_code)
    """
    try:
        tier = InviteAchievementTier.objects.get(pk=tier_id)
    except InviteAchievementTier.DoesNotExist:
        return None, "阶梯不存在", 404, 4072
    if not tier.is_active:
        return None, "该阶梯已停用", 400, 4074

    with transaction.atomic():
        FrontendUser.objects.select_for_update().filter(pk=user.pk).first()
        invited = count_direct_invites(user)
        if invited < tier.invite_threshold:
            return (
                None,
                f"有效邀请人数未满 {tier.invite_threshold}，暂不可领取",
                400,
                4075,
            )
        _, created = InviteAchievementClaim.objects.get_or_create(user=user, tier=tier)
        if not created:
            return None, "该档奖励已领取", 409, 4073
        wallet, _ = Wallet.objects.get_or_create(user=user)
        wallet = Wallet.objects.select_for_update().get(pk=wallet.pk)
        granted = grant_invite_achievement_rewards(wallet, tier)

    payload = {
        "tier": {
            "id": tier.id,
            "title": _bot_dynamic_title(tier.title, getattr(user, "preferred_language", None)),
            "invite_threshold": tier.invite_threshold,
        },
        "granted": granted,
        "invited_total": invited,
        "overview": build_invite_achievement_overview(user),
    }
    send_invite_achievement_claim_message(user, tier, granted, invited_total=invited)
    return (payload, None, 200, 0)
