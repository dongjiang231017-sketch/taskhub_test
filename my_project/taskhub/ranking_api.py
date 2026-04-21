"""
排行页：全站统计、任务榜、邀请榜、当前用户邀请数据与我的排名条。
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings
from django.db.models import Count, Min, Q, Sum
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from users.models import FrontendUser
from wallets.models import Transaction, Wallet

from .api_views import api_error, api_response, parse_positive_int, require_api_login
from .models import Task, TaskApplication
from .profile_center_api import _rank_position

_MONEY_QUANT = Decimal("0.01")


def _d_money(v) -> Decimal:
    if v is None:
        return Decimal("0.00")
    return Decimal(v).quantize(_MONEY_QUANT, rounding=ROUND_HALF_UP)


def _referrer_reward_usdt_sum(user: FrontendUser) -> Decimal:
    """推荐人钱包中「推荐奖励」USDT 累计（正数入账）。"""
    Wallet.objects.get_or_create(user=user)
    wallet = Wallet.objects.get(user=user)
    s = (
        Transaction.objects.filter(wallet=wallet, change_type="reward", amount__gt=0)
        .exclude(remark__icontains="TH Coin")
        .aggregate(s=Sum("amount"))["s"]
    )
    return _d_money(s)


def _child_completed_tasks_count(child: FrontendUser) -> int:
    return TaskApplication.objects.filter(
        applicant=child, status=TaskApplication.STATUS_ACCEPTED
    ).count()


def _user_task_commission_usdt(user: FrontendUser) -> Decimal:
    """个人通过做任务获得的 USDT（钱包 task_reward 正数合计，不含 TH）。"""
    Wallet.objects.get_or_create(user=user)
    wallet = Wallet.objects.get(user=user)
    s = (
        Transaction.objects.filter(wallet=wallet, change_type="task_reward", amount__gt=0)
        .exclude(remark__icontains="TH Coin")
        .aggregate(s=Sum("amount"))["s"]
    )
    return _d_money(s)


def _commission_rank_position(user: FrontendUser) -> int:
    """佣金榜名次：严格多于本人 task_reward USDT 累计的人数 + 1。"""
    my_amt = _user_task_commission_usdt(user)
    higher = (
        Transaction.objects.filter(change_type="task_reward", amount__gt=0)
        .exclude(remark__icontains="TH Coin")
        .values("wallet__user_id")
        .annotate(t=Sum("amount"))
        .filter(t__gt=my_amt)
        .count()
    )
    return higher + 1


def _commission_rank_and_percentile(user: FrontendUser) -> dict:
    rank = _commission_rank_position(user)
    total_users = FrontendUser.objects.filter(status=True).count() or 1
    surpassed = int(100 * max(0, total_users - rank) / total_users)
    return {
        "rank": rank,
        "task_commission_usdt": str(_user_task_commission_usdt(user)),
        "surpassed_users_percent": min(99, max(0, surpassed)),
    }


def _platform_operating_days() -> int:
    anchor = getattr(settings, "PLATFORM_STATS_ANCHOR_DATE", "").strip()
    if anchor:
        try:
            start = dt.date.fromisoformat(anchor)
        except ValueError:
            start = None
    else:
        start = None
    if start is None:
        umin = FrontendUser.objects.aggregate(m=Min("created_at"))["m"]
        tmin = Task.objects.aggregate(m=Min("created_at"))["m"]
        candidates = [x for x in (umin, tmin) if x is not None]
        if not candidates:
            return 1
        start = min(candidates).date()
    today = timezone.localdate()
    return max(1, (today - start).days + 1)


def _platform_total_tasks() -> int:
    return Task.objects.exclude(status=Task.STATUS_DRAFT).count()


def _platform_total_rewards_usdt() -> Decimal:
    """全站已发放任务奖励 USDT（账变 task_reward，正数，非 TH 备注）。"""
    s = (
        Transaction.objects.filter(change_type="task_reward", amount__gt=0)
        .exclude(remark__icontains="TH Coin")
        .aggregate(s=Sum("amount"))["s"]
    )
    return _d_money(s)


def _platform_total_users() -> int:
    return FrontendUser.objects.filter(status=True).count()


def _invite_link_for_user(user: FrontendUser, request) -> dict:
    """
    邀请链接优先级（对外只暴露一条可复制 URL：full_url）：
    1) 同时配置 TELEGRAM_BOT_USERNAME + TELEGRAM_MINI_APP_SHORT_NAME →
       https://t.me/<bot>/<short>?startapp=<prefix><invite_code>（Mini App 直链；载荷为邀请码便于辨认）
    2) 仅 TELEGRAM_BOT_USERNAME → https://t.me/<bot>?start=…（Bot 深链）
    3) INVITE_LINK_BASE_URL → 拼接 /invite/<code>
    4) 当前站点绝对路径 /invite/<code>
    """
    code = user.invite_code
    path = f"/invite/{code}"
    prefix = getattr(settings, "TELEGRAM_INVITE_START_PREFIX", "ref_") or "ref_"
    bot = (getattr(settings, "TELEGRAM_BOT_USERNAME", None) or "").strip().lstrip("@")
    short = (getattr(settings, "TELEGRAM_MINI_APP_SHORT_NAME", None) or "").strip()
    # 对外邀请链接统一用邀请码（不用 telegram_id，避免链接里暴露长数字 ID）
    start_arg = f"{prefix}{code}"
    out: dict = {"invite_code": code, "path": path}

    if bot:
        out["start_param"] = start_arg
        if short:
            out["full_url"] = f"https://t.me/{bot}/{short}?startapp={start_arg}"
            out["link_style"] = "telegram_mini_app_startapp"
        else:
            out["full_url"] = f"https://t.me/{bot}?start={start_arg}"
            out["link_style"] = "telegram_bot_start"
    else:
        base = (getattr(settings, "INVITE_LINK_BASE_URL", None) or "").strip().rstrip("/")
        if base:
            out["full_url"] = f"{base}{path}" if path.startswith("/") else f"{base}/{path}"
            out["link_style"] = "custom_base"
        else:
            out["full_url"] = request.build_absolute_uri(path) if request else path
            out["link_style"] = "site_absolute"

    return out


def _commission_rate() -> dict:
    r = getattr(settings, "INVITE_COMMISSION_RATE", Decimal("0.10"))
    if not isinstance(r, Decimal):
        r = Decimal(str(r))
    pct = int((r * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return {"decimal": str(r), "percent": pct, "label": f"{pct}% 返佣"}


def _user_public_card(u: FrontendUser) -> dict:
    return {
        "id": u.id,
        "username": u.username,
        "membership_level": u.membership_level,
        "avatar_url": None,
    }


@csrf_exempt
@require_http_methods(["GET"])
def rankings_platform_stats_api(request):
    """
    排行页顶部全站统计：任务总数、总发放奖励(USDT)、总用户数、运营天数。
    可不登录。
    """
    data = {
        "total_tasks": _platform_total_tasks(),
        "total_rewards_issued_usdt": str(_platform_total_rewards_usdt()),
        "total_users": _platform_total_users(),
        "operating_days": _platform_operating_days(),
        "currency_display_hint": "UI 可将 USDT 展示为 ¥ 或 $，与产品一致即可",
    }
    return api_response(data)


@csrf_exempt
@require_http_methods(["GET"])
def rankings_commission_leaderboard_api(request):
    """
    佣金榜：按个人做任务获得的 USDT 累计（账变 task_reward）降序分页。
    与「邀请榜」独立；可不登录。路径亦保留别名 `rankings/task-leaderboard/`。
    """
    try:
        page = parse_positive_int(request.GET.get("page", 1), "page", minimum=1)
        page_size = parse_positive_int(request.GET.get("page_size", 20), "page_size", minimum=1)
    except ValueError as exc:
        return api_error(str(exc), code=4016, status=400)
    page_size = min(page_size, 50)

    base = (
        Transaction.objects.filter(change_type="task_reward", amount__gt=0)
        .exclude(remark__icontains="TH Coin")
        .values("wallet__user_id")
        .annotate(task_commission_usdt=Sum("amount"))
        .order_by("-task_commission_usdt", "wallet__user_id")
    )
    total = base.count()
    offset = (page - 1) * page_size
    slice_rows = list(base[offset : offset + page_size])
    ids = [r["wallet__user_id"] for r in slice_rows]
    users_by_id = FrontendUser.objects.in_bulk(ids)
    count_by = {
        row["applicant_id"]: row["n"]
        for row in TaskApplication.objects.filter(
            applicant_id__in=ids, status=TaskApplication.STATUS_ACCEPTED
        )
        .values("applicant_id")
        .annotate(n=Count("id"))
    }
    items = []
    for idx, row in enumerate(slice_rows, start=offset + 1):
        uid = row["wallet__user_id"]
        u = users_by_id.get(uid)
        if not u:
            continue
        card = _user_public_card(u)
        card["rank"] = idx
        card["task_commission_usdt"] = str(_d_money(row["task_commission_usdt"]))
        card["completed_tasks"] = int(count_by.get(uid, 0))
        items.append(card)

    return api_response(
        {
            "leaderboard_type": "task_commission_usdt",
            "items": items,
            "pagination": {"page": page, "page_size": page_size, "total": total, "has_more": offset + len(items) < total},
        }
    )


@csrf_exempt
@require_http_methods(["GET"])
def rankings_invite_leaderboard_api(request):
    """邀请榜：按直接邀请人数降序分页；可不登录。"""
    try:
        page = parse_positive_int(request.GET.get("page", 1), "page", minimum=1)
        page_size = parse_positive_int(request.GET.get("page_size", 20), "page_size", minimum=1)
    except ValueError as exc:
        return api_error(str(exc), code=4016, status=400)
    page_size = min(page_size, 50)

    base = (
        FrontendUser.objects.filter(status=True)
        .annotate(invited_count=Count("children", filter=Q(children__status=True)))
        .filter(invited_count__gt=0)
        .order_by("-invited_count", "id")
    )
    total = base.count()
    offset = (page - 1) * page_size
    rows = list(base[offset : offset + page_size])
    items = []
    for idx, u in enumerate(rows, start=offset + 1):
        card = _user_public_card(u)
        card["rank"] = idx
        card["invited_count"] = u.invited_count
        items.append(card)

    return api_response(
        {
            "items": items,
            "pagination": {"page": page, "page_size": page_size, "total": total, "has_more": offset + len(items) < total},
        }
    )


def _invite_rank_and_percentile(user: FrontendUser) -> dict:
    my_invites = user.children.filter(status=True).count()
    higher = (
        FrontendUser.objects.filter(status=True)
        .annotate(c=Count("children", filter=Q(children__status=True)))
        .filter(c__gt=my_invites)
        .count()
    )
    rank = higher + 1
    total_users = FrontendUser.objects.filter(status=True).count() or 1
    surpassed = int(100 * max(0, total_users - rank) / total_users)
    return {"rank": rank, "invited_count": my_invites, "surpassed_users_percent": min(99, max(0, surpassed))}


def _task_rank_and_percentile(user: FrontendUser) -> dict:
    completed = _child_completed_tasks_count(user)
    rank = _rank_position(user, completed)
    total_users = FrontendUser.objects.filter(status=True).count() or 1
    surpassed = int(100 * max(0, total_users - rank) / max(total_users, 1))
    return {
        "rank": rank,
        "completed_tasks": completed,
        "surpassed_users_percent": min(99, max(0, surpassed)),
    }


@csrf_exempt
@require_api_login
@require_http_methods(["GET"])
def me_ranking_invite_overview_api(request):
    """
    邀请统计区：累计邀请、推荐奖励入账(USDT)、返佣比例说明、邀请链接。
    """
    user = request.api_user
    children = list(FrontendUser.objects.filter(referrer=user, status=True).order_by("-created_at"))
    total_invited = len(children)
    credited = _referrer_reward_usdt_sum(user)
    rate = _commission_rate()
    # 「预计收益」展示：已入账推荐奖励 + 按配置比例对下级已发任务奖励 USDT 的估算加总（未扣税，仅展示）
    child_task_reward_sum = Decimal("0")
    for ch in children:
        w, _ = Wallet.objects.get_or_create(user=ch)
        s = (
            Transaction.objects.filter(wallet=w, change_type="task_reward", amount__gt=0)
            .exclude(remark__icontains="TH Coin")
            .aggregate(s=Sum("amount"))["s"]
        )
        child_task_reward_sum += _d_money(s)
    est_extra = (child_task_reward_sum * Decimal(rate["decimal"])).quantize(_MONEY_QUANT, rounding=ROUND_HALF_UP)
    estimated_display = (credited + est_extra).quantize(_MONEY_QUANT, rounding=ROUND_HALF_UP)

    data = {
        "invite": {
            "total_invited": total_invited,
            "referral_credited_usdt": str(credited),
            "referral_estimated_display_usdt": str(estimated_display),
            "commission": rate,
            "note": "referral_credited_usdt 为钱包「推荐奖励」入账合计；referral_estimated_display_usdt 在其基础上叠加下级已入账任务奖励×返佣比例的估算，供 UI「预计收益」参考。",
        },
        "invite_link": _invite_link_for_user(user, request),
        "me": {
            "invite": _invite_rank_and_percentile(user),
            "task": _task_rank_and_percentile(user),
            "commission": _commission_rank_and_percentile(user),
            "user": _user_public_card(user),
            "total_contribution_usdt": str(credited),
        },
    }
    return api_response(data)


@csrf_exempt
@require_api_login
@require_http_methods(["GET"])
def me_ranking_invitees_api(request):
    """我的邀请明细：分页，含下级完成任务数与贡献返佣（按已入账推荐奖励比例分摊展示）。"""
    user = request.api_user
    try:
        page = parse_positive_int(request.GET.get("page", 1), "page", minimum=1)
        page_size = parse_positive_int(request.GET.get("page_size", 20), "page_size", minimum=1)
    except ValueError as exc:
        return api_error(str(exc), code=4016, status=400)
    page_size = min(page_size, 50)

    qs = (
        FrontendUser.objects.filter(referrer=user, status=True)
        .annotate(
            n_done=Count(
                "task_applications",
                filter=Q(task_applications__status=TaskApplication.STATUS_ACCEPTED),
            )
        )
        .order_by("-created_at")
    )
    total = qs.count()
    offset = (page - 1) * page_size
    children = list(qs[offset : offset + page_size])

    ref_total = _referrer_reward_usdt_sum(user)
    total_completed = TaskApplication.objects.filter(
        applicant__referrer=user,
        applicant__status=True,
        status=TaskApplication.STATUS_ACCEPTED,
    ).count()
    denom = Decimal(total_completed) if total_completed > 0 else Decimal("0")

    items = []
    for ch in children:
        n_done = ch.n_done
        if denom > 0 and ref_total > 0:
            share = (Decimal(n_done) / denom * ref_total).quantize(_MONEY_QUANT, rounding=ROUND_HALF_UP)
        else:
            share = Decimal("0.00")
        row = _user_public_card(ch)
        row["completed_tasks"] = n_done
        row["contribution_commission_usdt"] = str(share)
        row["commission_label"] = "贡献返佣"
        row["joined_at"] = ch.created_at.isoformat()
        items.append(row)

    return api_response(
        {
            "total_invited": total,
            "items": items,
            "pagination": {"page": page, "page_size": page_size, "total": total, "has_more": offset + len(items) < total},
            "commission_note": "contribution_commission_usdt 按当前全下级已完成任务数占比，分摊您钱包内「推荐奖励」USDT 累计，仅用于列表展示；与真实分佣明细以账变为准。",
        }
    )


@csrf_exempt
@require_api_login
@require_http_methods(["GET"])
def me_ranking_context_api(request):
    """排行页底栏：邀请排名、已录用任务数排名、做任务佣金(USDT)排名、推荐奖励累计。"""
    user = request.api_user
    credited = _referrer_reward_usdt_sum(user)
    data = {
        "user": _user_public_card(user),
        "task": _task_rank_and_percentile(user),
        "commission": _commission_rank_and_percentile(user),
        "invite": _invite_rank_and_percentile(user),
        "total_contribution_usdt": str(credited),
    }
    return api_response(data)
