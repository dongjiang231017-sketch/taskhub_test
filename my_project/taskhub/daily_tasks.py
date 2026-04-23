"""每日任务：后台配置、按自然日统计进度、领取发奖。"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from users.models import FrontendUser
from wallets.models import Transaction, Wallet

from .api_views import _task_application_truly_done
from .models import DailyTaskDayClaim, DailyTaskDefinition, TaskApplication
from .telegram_push import _bot_dynamic_title, send_daily_task_claim_message


def _app_completion_local_date(app: TaskApplication, task) -> date | None:
    """任务「完结」所在自然日（与 api_views._task_application_truly_done 一致）。"""
    if not _task_application_truly_done(app, task):
        return None
    if app.reward_paid_at:
        return timezone.localdate(app.reward_paid_at)
    anchor = app.decided_at or app.updated_at
    if anchor is None:
        return None
    return timezone.localdate(anchor)


def _metric_progress(user: FrontendUser, metric_code: str, on_date: date) -> int:
    if metric_code == DailyTaskDefinition.METRIC_PLATFORM_TASKS_DONE_TODAY:
        qs = TaskApplication.objects.filter(
            applicant=user,
            status=TaskApplication.STATUS_ACCEPTED,
        ).select_related("task")
        n = 0
        for app in qs:
            d = _app_completion_local_date(app, app.task)
            if d == on_date:
                n += 1
        return n
    return 0


def _tier_status(current: int, target: int, claimed: bool) -> str:
    if claimed:
        return "claimed"
    if current >= target:
        return "claimable"
    return "locked"


def build_daily_tasks_payload(user: FrontendUser) -> dict:
    today = timezone.localdate()
    defs = list(
        DailyTaskDefinition.objects.filter(is_active=True).order_by("sort_order", "id")
    )
    def_ids = [d.id for d in defs]
    if def_ids:
        claimed_keys = set(
            DailyTaskDayClaim.objects.filter(
                user=user, on_date=today, definition_id__in=def_ids
            ).values_list("definition_id", flat=True)
        )
    else:
        claimed_keys = set()
    progress_cache: dict[str, int] = {}

    def progress_for(definition: DailyTaskDefinition) -> int:
        code = definition.metric_code
        if code not in progress_cache:
            progress_cache[code] = _metric_progress(user, code, today)
        return progress_cache[code]

    tasks_out = []
    for d in defs:
        cur = progress_for(d)
        claimed = d.id in claimed_keys
        tasks_out.append(
            {
                "id": d.id,
                "sort_order": d.sort_order,
                "title": _bot_dynamic_title(d.title, getattr(user, "preferred_language", None)),
                "metric_code": d.metric_code,
                "target_count": d.target_count,
                "reward_usdt": str(d.reward_usdt),
                "reward_th": str(d.reward_th),
                "status": _tier_status(cur, d.target_count, claimed),
                "progress_current": cur,
                "progress_target": d.target_count,
            }
        )

    total = len(tasks_out)
    claimed_count = sum(1 for t in tasks_out if t["status"] == "claimed")
    achieved_count = sum(1 for t in tasks_out if t["progress_current"] >= t["progress_target"])

    return {
        "day": today.isoformat(),
        "timezone": str(timezone.get_current_timezone()),
        "reset_note": "按服务器配置时区的自然日统计，每日零点起算新进度；领取记录按日隔离。",
        "summary": {
            "total_tasks": total,
            "claimed_count": claimed_count,
            "achieved_count": achieved_count,
        },
        "tasks": tasks_out,
    }


def grant_daily_task_rewards(wallet: Wallet, definition: DailyTaskDefinition) -> dict:
    granted = {"usdt": "0", "th_coin": "0"}
    ru, rt = definition.reward_usdt, definition.reward_th
    if ru <= Decimal("0") and rt <= Decimal("0"):
        return granted

    old_b, old_f = wallet.balance, wallet.frozen
    new_b = old_b + max(ru, Decimal("0"))
    new_f = old_f + max(rt, Decimal("0"))
    remark_base = f"每日任务：{definition.title}"
    if ru > 0:
        Transaction.objects.create(
            wallet=wallet,
            asset=Transaction.ASSET_USDT,
            amount=ru,
            before_balance=old_b,
            after_balance=new_b,
            change_type="daily_task",
            remark=f"{remark_base}·USDT",
        )
    if rt > 0:
        Transaction.objects.create(
            wallet=wallet,
            asset=Transaction.ASSET_TH_COIN,
            amount=rt,
            before_balance=old_f,
            after_balance=new_f,
            change_type="daily_task",
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


def claim_daily_task_definition(
    user: FrontendUser, definition_id: int
) -> tuple[dict | None, str | None, int, int]:
    today = timezone.localdate()
    try:
        definition = DailyTaskDefinition.objects.get(pk=definition_id)
    except DailyTaskDefinition.DoesNotExist:
        return None, "每日任务不存在", 404, 4081
    if not definition.is_active:
        return None, "该每日任务已停用", 400, 4083

    with transaction.atomic():
        FrontendUser.objects.select_for_update().filter(pk=user.pk).first()
        current = _metric_progress(user, definition.metric_code, today)
        if current < definition.target_count:
            return (
                None,
                f"当日进度未满 {definition.target_count}，暂不可领取",
                400,
                4084,
            )
        _, created = DailyTaskDayClaim.objects.get_or_create(
            user=user,
            definition=definition,
            on_date=today,
        )
        if not created:
            return None, "今日该任务奖励已领取", 409, 4082
        wallet, _ = Wallet.objects.get_or_create(user=user)
        wallet = Wallet.objects.select_for_update().get(pk=wallet.pk)
        granted = grant_daily_task_rewards(wallet, definition)

    payload = {
        "day": today.isoformat(),
        "definition": {
            "id": definition.id,
            "title": _bot_dynamic_title(definition.title, getattr(user, "preferred_language", None)),
            "target_count": definition.target_count,
        },
        "granted": granted,
        "progress_current": current,
    }
    send_daily_task_claim_message(user, definition, granted)
    return (payload, None, 200, 0)
