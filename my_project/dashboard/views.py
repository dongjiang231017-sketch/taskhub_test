from __future__ import annotations

import json
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import Count, Q, Sum
from django.shortcuts import render
from django.utils import timezone

from staking.models import StakeRecord
from taskhub.models import CheckInRecord, DailyTaskDayClaim, Task, TaskApplication
from users.models import FrontendUser
from wallets.models import Transaction, Wallet, WithdrawalRequest


ZERO = Decimal("0")
MONEY = Decimal("0.01")
REWARD_TYPES = (
    "task_reward",
    "reward",
    "check_in",
    "check_in_makeup",
    "invite_achievement",
    "daily_task",
)


def _decimal(value) -> Decimal:
    if value is None:
        return ZERO
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value or "0"))


def _money(value) -> str:
    return str(_decimal(value).quantize(MONEY, rounding=ROUND_HALF_UP))


def _number(value) -> str:
    return f"{int(value or 0):,}"


def _chart_number(value) -> float:
    return float(_decimal(value).quantize(MONEY, rounding=ROUND_HALF_UP))


def _sum(qs, field="amount") -> Decimal:
    return _decimal(qs.aggregate(total=Sum(field)).get("total"))


def _count_series(qs, date_field: str, days: list, start_date) -> list[int]:
    key = f"{date_field}__date" if date_field != "on_date" else "on_date"
    rows = {
        row[key]: row["value"]
        for row in qs.filter(**{f"{key}__gte": start_date}).values(key).annotate(value=Count("id"))
    }
    return [int(rows.get(day, 0) or 0) for day in days]


def _sum_series(qs, date_field: str, days: list, start_date, field="amount") -> list[float]:
    key = f"{date_field}__date"
    rows = {
        row[key]: _decimal(row["value"])
        for row in qs.filter(**{f"{key}__gte": start_date}).values(key).annotate(value=Sum(field))
    }
    return [_chart_number(rows.get(day, ZERO)) for day in days]


def _pct(part: int | Decimal, total: int | Decimal) -> str:
    total_d = _decimal(total)
    if total_d <= 0:
        return "0.0%"
    return f"{(_decimal(part) * Decimal('100') / total_d).quantize(Decimal('0.1'))}%"


def _status_rows(choices, counts: dict) -> list[dict]:
    return [
        {"name": label, "value": int(counts.get(key, 0) or 0)}
        for key, label in choices
        if int(counts.get(key, 0) or 0) > 0
    ]


def _choice_label(choices, key: str) -> str:
    return dict(choices).get(key, key or "未配置")


@staff_member_required
def dashboard_view(request):
    now = timezone.localtime(timezone.now())
    today = now.date()
    days = [today - timedelta(days=i) for i in range(29, -1, -1)]
    start_date = days[0]
    labels = [day.strftime("%m-%d") for day in days]
    last_7_date = today - timedelta(days=6)

    users = FrontendUser.objects.all()
    tasks = Task.objects.all()
    applications = TaskApplication.objects.select_related("task", "applicant")
    wallets = Wallet.objects.all()
    transactions = Transaction.objects.select_related("wallet", "wallet__user")
    withdrawals = WithdrawalRequest.objects.select_related("user")

    total_members = users.count()
    active_members = users.filter(status=True).count()
    disabled_members = total_members - active_members
    telegram_members = users.filter(telegram_id__isnull=False).count()
    invited_members = users.filter(referrer_id__isnull=False).count()
    today_members = users.filter(created_at__date=today).count()
    week_members = users.filter(created_at__date__gte=last_7_date).count()

    total_tasks = tasks.count()
    open_tasks = tasks.filter(status=Task.STATUS_OPEN).count()
    mandatory_tasks = tasks.filter(is_mandatory=True).count()
    social_tasks = tasks.filter(
        interaction_type__in=(Task.INTERACTION_FOLLOW, Task.INTERACTION_LIKE, Task.INTERACTION_COMMENT)
    ).count()

    total_applications = applications.count()
    pending_applications = applications.filter(status=TaskApplication.STATUS_PENDING).count()
    accepted_applications = applications.filter(status=TaskApplication.STATUS_ACCEPTED).count()
    cancelled_applications = applications.filter(status=TaskApplication.STATUS_CANCELLED).count()
    rejected_applications = applications.filter(status=TaskApplication.STATUS_REJECTED).count()
    today_applications = applications.filter(created_at__date=today).count()
    today_completed = applications.filter(status=TaskApplication.STATUS_ACCEPTED, decided_at__date=today).count()
    completion_rate = _pct(accepted_applications, total_applications)

    checkins_today = CheckInRecord.objects.filter(on_date=today).count()
    checkins_7d_users = (
        CheckInRecord.objects.filter(on_date__gte=last_7_date).values("user_id").distinct().count()
    )
    daily_claims_today = DailyTaskDayClaim.objects.filter(on_date=today).count()
    checkin_rate = _pct(checkins_today, active_members)

    reward_tx = transactions.filter(change_type__in=REWARD_TYPES, amount__gt=0)
    task_reward_tx = transactions.filter(change_type="task_reward", amount__gt=0)
    referral_reward_tx = transactions.filter(change_type="reward", amount__gt=0)
    reward_today_usdt = _sum(reward_tx.filter(asset=Transaction.ASSET_USDT, created_at__date=today))
    reward_today_th = _sum(reward_tx.filter(asset=Transaction.ASSET_TH_COIN, created_at__date=today))
    reward_30d_usdt = _sum(reward_tx.filter(asset=Transaction.ASSET_USDT, created_at__date__gte=start_date))
    reward_30d_th = _sum(reward_tx.filter(asset=Transaction.ASSET_TH_COIN, created_at__date__gte=start_date))
    referral_30d_usdt = _sum(referral_reward_tx.filter(created_at__date__gte=start_date))

    wallet_usdt = _sum(wallets, "balance")
    wallet_th = _sum(wallets, "frozen")
    active_stake_amount = _sum(StakeRecord.objects.filter(status="active"), "amount")
    active_stake_count = StakeRecord.objects.filter(status="active").count()
    stake_income_total = _sum(StakeRecord.objects.all(), "total_earned")

    processing_withdrawals = withdrawals.filter(status=WithdrawalRequest.STATUS_PROCESSING)
    completed_withdrawals = withdrawals.filter(status=WithdrawalRequest.STATUS_COMPLETED)
    withdrawal_processing_count = processing_withdrawals.count()
    withdrawal_processing_amount = _sum(processing_withdrawals, "amount")
    withdrawal_today_amount = _sum(withdrawals.filter(created_at__date=today), "amount")
    withdrawal_30d_completed = _sum(completed_withdrawals.filter(updated_at__date__gte=start_date), "amount")

    registrations = _count_series(users, "created_at", days, start_date)
    base_members = users.filter(created_at__date__lt=start_date).count()
    cumulative_members = []
    running_members = base_members
    for value in registrations:
        running_members += value
        cumulative_members.append(running_members)

    application_series = _count_series(applications, "created_at", days, start_date)
    completed_series = _count_series(
        applications.filter(status=TaskApplication.STATUS_ACCEPTED, decided_at__isnull=False),
        "decided_at",
        days,
        start_date,
    )
    checkin_series = _count_series(CheckInRecord.objects.all(), "on_date", days, start_date)
    usdt_reward_series = _sum_series(
        reward_tx.filter(asset=Transaction.ASSET_USDT), "created_at", days, start_date
    )
    th_reward_series = _sum_series(
        reward_tx.filter(asset=Transaction.ASSET_TH_COIN), "created_at", days, start_date
    )
    withdrawal_series = _sum_series(withdrawals, "created_at", days, start_date, "amount")
    stake_series = _sum_series(StakeRecord.objects.all(), "created_at", days, start_date, "amount")

    task_status_counts = dict(tasks.values_list("status").annotate(value=Count("id")))
    application_status_counts = dict(applications.values_list("status").annotate(value=Count("id")))
    withdrawal_status_counts = dict(withdrawals.values_list("status").annotate(value=Count("id")))
    task_type_rows = _status_rows(
        Task.INTERACTION_CHOICES,
        dict(tasks.values_list("interaction_type").annotate(value=Count("id"))),
    )

    binding_rows_raw = (
        applications.filter(
            status=TaskApplication.STATUS_ACCEPTED,
            task__interaction_type=Task.INTERACTION_ACCOUNT_BINDING,
        )
        .values("task__binding_platform")
        .annotate(value=Count("id"))
        .order_by("-value")
    )
    binding_rows = [
        {
            "name": _choice_label(Task.BINDING_PLATFORM_CHOICES, row["task__binding_platform"]),
            "value": row["value"],
        }
        for row in binding_rows_raw
        if row["task__binding_platform"]
    ]

    platform_task_rows_raw = (
        applications.filter(status=TaskApplication.STATUS_ACCEPTED)
        .exclude(task__binding_platform="")
        .values("task__binding_platform")
        .annotate(value=Count("id"))
        .order_by("-value")
    )
    platform_task_rows = [
        {
            "name": _choice_label(Task.BINDING_PLATFORM_CHOICES, row["task__binding_platform"]),
            "value": row["value"],
        }
        for row in platform_task_rows_raw
    ]

    top_tasks = []
    top_task_qs = (
        tasks.annotate(
            accepted_count=Count(
                "applications",
                filter=Q(applications__status=TaskApplication.STATUS_ACCEPTED),
            ),
            pending_count=Count(
                "applications",
                filter=Q(applications__status=TaskApplication.STATUS_PENDING),
            ),
        )
        .filter(accepted_count__gt=0)
        .order_by("-accepted_count", "-id")[:8]
    )
    for task in top_task_qs:
        top_tasks.append(
            {
                "id": task.id,
                "title": task.title,
                "type": task.get_interaction_type_display(),
                "platform": task.get_binding_platform_display() if task.binding_platform else "—",
                "accepted": task.accepted_count,
                "pending": task.pending_count,
                "usdt": _money(_decimal(task.reward_usdt) * task.accepted_count),
                "th": _money(_decimal(task.reward_th_coin) * task.accepted_count),
            }
        )

    recent_withdrawals = [
        {
            "id": item.id,
            "user": item.user.username,
            "amount": _money(item.amount),
            "fee": _money(item.fee),
            "status": item.get_status_display(),
            "created_at": timezone.localtime(item.created_at).strftime("%m-%d %H:%M"),
        }
        for item in withdrawals.order_by("-created_at")[:8]
    ]

    alert_items = [
        {
            "label": "待处理任务报名",
            "value": pending_applications,
            "hint": "需要运营审核或用户继续校验",
            "level": "warn" if pending_applications else "ok",
            "url": "/admin/taskhub/taskapplication/?status__exact=pending",
        },
        {
            "label": "待处理提现",
            "value": withdrawal_processing_count,
            "hint": f"金额 { _money(withdrawal_processing_amount) } USDT",
            "level": "danger" if withdrawal_processing_count else "ok",
            "url": "/admin/wallets/withdrawalrequest/?status__exact=processing",
        },
        {
            "label": "开放任务库存",
            "value": open_tasks,
            "hint": "前台当前可报名任务",
            "level": "ok" if open_tasks else "warn",
            "url": "/admin/taskhub/task/?status__exact=open",
        },
        {
            "label": "今日签到活跃",
            "value": checkins_today,
            "hint": f"活跃会员覆盖 {checkin_rate}",
            "level": "ok",
            "url": "/admin/taskhub/checkinrecord/",
        },
    ]

    kpi_cards = [
        {
            "label": "总会员",
            "value": _number(total_members),
            "sub": f"今日 +{today_members} / 7日 +{week_members}",
            "tone": "blue",
        },
        {
            "label": "今日完成任务",
            "value": _number(today_completed),
            "sub": f"总完成 {accepted_applications}，完成率 {completion_rate}",
            "tone": "green",
        },
        {
            "label": "今日发放奖励",
            "value": f"{_money(reward_today_usdt)} USDT",
            "sub": f"{_money(reward_today_th)} TH Coin",
            "tone": "amber",
        },
        {
            "label": "待处理提现",
            "value": _number(withdrawal_processing_count),
            "sub": f"{_money(withdrawal_processing_amount)} USDT",
            "tone": "red",
        },
    ]

    metric_groups = [
        {
            "title": "用户增长",
            "items": [
                ("启用会员", _number(active_members)),
                ("禁用会员", _number(disabled_members)),
                ("Telegram 登录", _number(telegram_members)),
                ("有上级推荐", _number(invited_members)),
            ],
        },
        {
            "title": "任务运营",
            "items": [
                ("任务总数", _number(total_tasks)),
                ("开放任务", _number(open_tasks)),
                ("首页必做", _number(mandatory_tasks)),
                ("社交任务", _number(social_tasks)),
            ],
        },
        {
            "title": "任务报名",
            "items": [
                ("今日报名", _number(today_applications)),
                ("待处理", _number(pending_applications)),
                ("已完成", _number(accepted_applications)),
                ("取消/拒绝", _number(cancelled_applications + rejected_applications)),
            ],
        },
        {
            "title": "资产负债",
            "items": [
                ("钱包 USDT", _money(wallet_usdt)),
                ("钱包 TH Coin", _money(wallet_th)),
                ("活跃质押金额", _money(active_stake_amount)),
                ("活跃质押笔数", _number(active_stake_count)),
                ("累计质押收益", _money(stake_income_total)),
            ],
        },
        {
            "title": "活跃行为",
            "items": [
                ("今日签到", _number(checkins_today)),
                ("7日签到用户", _number(checkins_7d_users)),
                ("今日每日任务领取", _number(daily_claims_today)),
                ("签到覆盖", checkin_rate),
            ],
        },
        {
            "title": "资金结算",
            "items": [
                ("今日提现申请", _money(withdrawal_today_amount)),
                ("30日已完成提现", _money(withdrawal_30d_completed)),
                ("30日 USDT 奖励", _money(reward_30d_usdt)),
                ("30日 TH 奖励", _money(reward_30d_th)),
                ("30日推荐奖励", _money(referral_30d_usdt)),
            ],
        },
    ]

    charts = {
        "labels": labels,
        "registrations": registrations,
        "cumulativeMembers": cumulative_members,
        "applications": application_series,
        "completed": completed_series,
        "checkins": checkin_series,
        "usdtRewards": usdt_reward_series,
        "thRewards": th_reward_series,
        "withdrawals": withdrawal_series,
        "stakes": stake_series,
        "taskStatuses": _status_rows(Task.STATUS_CHOICES, task_status_counts),
        "applicationStatuses": _status_rows(TaskApplication.STATUS_CHOICES, application_status_counts),
        "withdrawalStatuses": _status_rows(WithdrawalRequest.STATUS_CHOICES, withdrawal_status_counts),
        "taskTypes": task_type_rows,
        "bindingPlatforms": binding_rows,
        "platformTasks": platform_task_rows,
        "assetBars": [
            {"name": "钱包 USDT", "value": _chart_number(wallet_usdt)},
            {"name": "活跃质押", "value": _chart_number(active_stake_amount)},
            {"name": "30日发奖 USDT", "value": _chart_number(reward_30d_usdt)},
            {"name": "30日提现", "value": _chart_number(withdrawal_30d_completed)},
        ],
    }

    context = {
        "generated_at": now.strftime("%Y-%m-%d %H:%M:%S"),
        "kpi_cards": kpi_cards,
        "metric_groups": metric_groups,
        "alert_items": alert_items,
        "top_tasks": top_tasks,
        "recent_withdrawals": recent_withdrawals,
        "charts_json": json.dumps(charts, ensure_ascii=False),
    }
    return render(request, "dashboard/dashboard.html", context)
