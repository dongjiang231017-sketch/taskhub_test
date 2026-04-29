"""邀请拉新活动规则聚合。"""

from __future__ import annotations

from decimal import Decimal

from django.db.utils import OperationalError, ProgrammingError

from .models import MembershipLevelConfig, ReferralRewardConfig, TeamLeaderTier
from .referral_config import get_referral_reward_rates


def _pct(rate: Decimal) -> str:
    value = (Decimal(str(rate)) * Decimal("100")).normalize()
    return f"{value}%"


def _money(value: Decimal) -> str:
    return str(Decimal(str(value)).quantize(Decimal("0.01")))


def _membership_payload(level: MembershipLevelConfig) -> dict:
    limit = level.daily_official_task_limit
    if level.unlimited_tasks or limit is None:
        limit_label = "不限"
    else:
        limit_label = f"{limit} 次/天"
    return {
        "id": level.id,
        "level": level.level,
        "name": level.name,
        "join_fee_usdt": _money(level.join_fee_usdt),
        "withdraw_fee_rate": str(level.withdraw_fee_rate),
        "withdraw_fee_rate_label": _pct(level.withdraw_fee_rate),
        "can_claim_free_tasks": level.can_claim_free_tasks,
        "can_claim_official_tasks": level.can_claim_official_tasks,
        "can_claim_high_commission_tasks": level.can_claim_high_commission_tasks,
        "daily_official_task_limit": limit,
        "daily_official_task_limit_label": limit_label,
        "unlimited_tasks": level.unlimited_tasks,
        "description": level.description,
    }


def _team_tier_payload(tier: TeamLeaderTier) -> dict:
    period_label = tier.get_target_period_display()
    return {
        "id": tier.id,
        "name": tier.name,
        "direct_vip_count": tier.direct_vip_count,
        "team_recharge_target_usdt": _money(tier.team_recharge_target_usdt),
        "target_period": tier.target_period,
        "target_period_label": period_label,
        "team_performance_rate": str(tier.team_performance_rate),
        "team_performance_rate_label": _pct(tier.team_performance_rate),
        "description": tier.description,
    }


def build_invite_activity_rules_payload(user=None) -> dict:
    """前台 / 机器人可直接展示的邀请拉新活动规则。"""

    try:
        config = ReferralRewardConfig.get()
        title = config.activity_title
        intro = config.activity_intro
        levels = list(MembershipLevelConfig.objects.filter(is_active=True).order_by("sort_order", "level"))
        tiers = list(TeamLeaderTier.objects.filter(is_active=True).order_by("sort_order", "id"))
    except (ProgrammingError, OperationalError):
        title = "关于任务邀请好友拉新活动会员等级"
        intro = "邀请好友加入 TaskHub，完成任务、充值会员与团队成长都可按后台配置获得奖励。"
        levels = []
        tiers = []

    rates = get_referral_reward_rates()
    membership_levels = [_membership_payload(level) for level in levels]
    team_leader_tiers = [_team_tier_payload(tier) for tier in tiers]

    data = {
        "title": title,
        "intro": intro,
        "membership_levels": membership_levels,
        "commission_model": {
            "recharge": {
                "level_1_rate": str(rates["recharge_direct_rate"]),
                "level_1_rate_label": _pct(rates["recharge_direct_rate"]),
                "level_2_rate": str(rates["recharge_second_rate"]),
                "level_2_rate_label": _pct(rates["recharge_second_rate"]),
                "description": "下级每成功充值 1 笔后，一级上级可获得充值金额对应比例佣金，二级上级可继续获得二级充值佣金。",
            },
            "task": {
                "level_1_rate": str(rates["task_direct_rate"]),
                "level_1_rate_label": _pct(rates["task_direct_rate"]),
                "level_2_rate": str(rates["task_second_rate"]),
                "level_2_rate_label": _pct(rates["task_second_rate"]),
                "description": "下级完成任务并成功入账后，一级上级按任务 USDT 奖励拿一级分成，二级上级继续拿二级分成。",
            },
        },
        "team_leader_tiers": team_leader_tiers,
        "rendered_sections": [
            {
                "title": "会员等级",
                "items": [
                    (
                        f"{item['name']}：加入费用 {item['join_fee_usdt']} USDT；"
                        f"VIP任务专区 {item['daily_official_task_limit_label']}；"
                        f"提现手续费 {item['withdraw_fee_rate_label']}"
                    )
                    for item in membership_levels
                ],
            },
            {
                "title": "动态收益：二级分佣模型",
                "items": [
                    f"一级充值佣金：{_pct(rates['recharge_direct_rate'])}",
                    f"二级充值佣金：{_pct(rates['recharge_second_rate'])}",
                    f"一级任务分成：{_pct(rates['task_direct_rate'])}",
                    f"二级任务分成：{_pct(rates['task_second_rate'])}",
                ],
            },
            {
                "title": "团队长（超级代理）扶持政策",
                "items": [
                    (
                        f"{item['name']}：直推 {item['direct_vip_count']} 个 VIP；"
                        f"{item['target_period_label']}团队充值 {item['team_recharge_target_usdt']} USDT；"
                        f"额外提成 {item['team_performance_rate_label']}"
                    )
                    for item in team_leader_tiers
                ],
            },
        ],
        "configurable_in_admin": True,
    }
    if user is not None:
        data["current_user_level"] = int(user.membership_level or 0)
    return data
