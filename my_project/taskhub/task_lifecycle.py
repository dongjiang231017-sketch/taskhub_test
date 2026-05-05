"""任务与报名生命周期：接取人数、满员/到期收尾、待处理超时。"""

from __future__ import annotations

import random
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings
from django.db import DEFAULT_DB_ALIAS, connections, transaction
from django.db.models import F
from django.utils import timezone

from .models import PlatformStatsDisplayConfig, Task, TaskApplication


def _task_has_positive_display_reward(task: Task) -> bool:
    u = task.reward_usdt if task.reward_usdt is not None else Decimal("0")
    t = task.reward_th_coin if task.reward_th_coin is not None else Decimal("0")
    return u > Decimal("0") or t > Decimal("0")


def _accepted_application_truly_done(application: TaskApplication, task: Task) -> bool:
    """与 api_views._task_application_truly_done 一致，避免 task_lifecycle 依赖 api_views 循环引用。"""
    if application.status != TaskApplication.STATUS_ACCEPTED:
        return False
    if application.reward_paid_at:
        return True
    if not _task_has_positive_display_reward(task):
        return True
    return False


def release_incomplete_applications_for_task_ids(task_ids: list[int]) -> int:
    """
    任务已不可接时：取消仍待处理、或已录用但未结奖的报名，释放唯一约束以便重新开放后可再次报名。
    满员关单（completed 且 deadline 未到）不在此路径调用，以免误清仍在进行的已录用。
    """
    if not task_ids:
        return 0
    now = timezone.now()
    n = 0
    apps = TaskApplication.objects.filter(
        task_id__in=task_ids,
        status__in=(TaskApplication.STATUS_PENDING, TaskApplication.STATUS_ACCEPTED),
    ).select_related("task")
    for app in apps.iterator(chunk_size=500):
        if app.status == TaskApplication.STATUS_ACCEPTED and _accepted_application_truly_done(app, app.task):
            continue
        updated = TaskApplication.objects.filter(
            pk=app.pk,
            status__in=(TaskApplication.STATUS_PENDING, TaskApplication.STATUS_ACCEPTED),
        ).update(status=TaskApplication.STATUS_CANCELLED, decided_at=now)
        n += int(updated)
    return n


def task_terminal_should_release_takers(task: Task) -> bool:
    """
    任务保存为「不可再接」时，是否应自动释放未完成报名者。
    - closed / draft：始终释放。
    - completed：仅当 deadline 已过（含到期关单）时释放；满员提前 completed 且 deadline 未到则不释放。
    """
    if task.status in (Task.STATUS_OPEN, Task.STATUS_IN_PROGRESS):
        return False
    if task.status in (Task.STATUS_CLOSED, Task.STATUS_DRAFT):
        return True
    if task.status == Task.STATUS_COMPLETED:
        if task.deadline and task.deadline < timezone.now():
            return True
        return False
    return False


def is_mandatory_account_binding(task: Task) -> bool:
    """首页必做 + 账号绑定：每账号独立完成一次，不因人数关闭整单。"""
    return bool(
        task.is_mandatory
        and task.interaction_type == Task.INTERACTION_ACCOUNT_BINDING
        and task.binding_platform
    )


def is_mandatory_no_slot_cap(task: Task) -> bool:
    """
    首页必做且不按传统「需求人数」关单/占坑的玩法（账号绑定、加入 Telegram 群等）。
    与 is_mandatory_account_binding 配合：凡需「每人独立完成」的必做卡片，都应走本判断。
    """
    if not task.is_mandatory:
        return False
    if is_mandatory_account_binding(task):
        return True
    if task.interaction_type == Task.INTERACTION_JOIN_COMMUNITY:
        return True
    return False


def effective_applicants_limit(task: Task) -> int:
    """需求人数至少按 1 计，避免后台误填 0 导致 `active_taker_count >= limit` 恒成立、无人可报名。"""
    n = int(task.applicants_limit or 0)
    return n if n >= 1 else 1


def active_taker_count(task: Task) -> int:
    """接取人数：待处理 + 已录用（每人至多一条报名）。"""
    return task.applications.filter(
        status__in=(TaskApplication.STATUS_PENDING, TaskApplication.STATUS_ACCEPTED)
    ).count()


def task_pending_can_expire(task: Task) -> bool:
    """是否适用「接取后须在超时内完成」。
    传统 interaction=none 悬赏仍等待发布人审核；其余玩法统一支持超时自动失效。
    """
    return task.interaction_type != Task.INTERACTION_NONE


def _pending_timeout_minutes() -> int:
    return max(1, int(getattr(settings, "TASK_PENDING_APPLICATION_TIMEOUT_MINUTES", 5)))


def touch_pending_application_activity(application_id: int) -> None:
    """用户仍在继续完成/校验时，刷新 pending 报名的最近活跃时间，避免误判超时。"""
    TaskApplication.objects.filter(pk=application_id, status=TaskApplication.STATUS_PENDING).update(
        updated_at=timezone.now()
    )


def _expire_stale_pending_queryset(queryset) -> int:
    n = 0
    for app in queryset.select_related("task").iterator(chunk_size=200):
        if not task_pending_can_expire(app.task):
            continue
        u = TaskApplication.objects.filter(pk=app.pk, status=TaskApplication.STATUS_PENDING).update(
            status=TaskApplication.STATUS_CANCELLED,
            decided_at=timezone.now(),
        )
        if u:
            n += 1
    return n


def maybe_mark_task_completed_when_slots_full(task_id: int) -> None:
    """普通任务：接取人数已满则任务标为已完成，不再接新单；已在席的待处理可继续完成。"""
    connections[DEFAULT_DB_ALIAS].close()
    with transaction.atomic():
        task = Task.objects.select_for_update().get(pk=task_id)
        if task.status != Task.STATUS_OPEN or is_mandatory_no_slot_cap(task):
            return
        if active_taker_count(task) < effective_applicants_limit(task):
            return
        now = timezone.now()
        Task.objects.filter(pk=task.pk, status=Task.STATUS_OPEN).update(
            status=Task.STATUS_COMPLETED,
            updated_at=now,
        )


def after_publisher_accepts_application(task: Task) -> None:
    """发布人录用后：必做绑定不关任务；普通任务录用人数达到 applicants_limit 则关单并取消其余待处理。"""
    if is_mandatory_no_slot_cap(task):
        return
    with transaction.atomic():
        task = Task.objects.select_for_update().get(pk=task.pk)
        if task.status != Task.STATUS_OPEN:
            return
        accepted = task.applications.filter(status=TaskApplication.STATUS_ACCEPTED).count()
        if accepted < effective_applicants_limit(task):
            return
        now = timezone.now()
        Task.objects.filter(pk=task.pk, status=Task.STATUS_OPEN).update(
            status=Task.STATUS_COMPLETED,
            updated_at=now,
        )
        TaskApplication.objects.filter(task=task, status=TaskApplication.STATUS_PENDING).update(
            status=TaskApplication.STATUS_CANCELLED,
            decided_at=now,
        )


def expire_stale_pending_applications() -> int:
    """将超过设定分钟仍处于 pending 的报名取消（仅限时类玩法）。"""
    cutoff = timezone.now() - timedelta(minutes=_pending_timeout_minutes())
    candidates = TaskApplication.objects.filter(
        status=TaskApplication.STATUS_PENDING,
        updated_at__lt=cutoff,
    )
    return _expire_stale_pending_queryset(candidates)


def expire_stale_pending_applications_for_applicant(applicant_id: int, *, task_id: int | None = None) -> int:
    """按用户（可选再按任务）即时释放已超时的 pending 报名。"""
    cutoff = timezone.now() - timedelta(minutes=_pending_timeout_minutes())
    candidates = TaskApplication.objects.filter(
        applicant_id=applicant_id,
        status=TaskApplication.STATUS_PENDING,
        updated_at__lt=cutoff,
    )
    if task_id is not None:
        candidates = candidates.filter(task_id=task_id)
    return _expire_stale_pending_queryset(candidates)


def release_stale_takers_when_completed_deadline_passed() -> int:
    """
    任务已是 completed 且 deadline 已过，但报名行可能仍为 pending/accepted（例如先满员关单再到期）。
    由 cron 与 close_tasks_past_deadline 配合调用，幂等。
    """
    now = timezone.now()
    ids = list(
        Task.objects.filter(
            status=Task.STATUS_COMPLETED,
            deadline__isnull=False,
            deadline__lt=now,
        ).values_list("pk", flat=True)
    )
    return release_incomplete_applications_for_task_ids(ids)


def close_tasks_past_deadline() -> int:
    """截止时间已过且仍为可报名的任务标记为已完成，并释放未完成报名（便于再次开放后重新接）。"""
    now = timezone.now()
    qs = Task.objects.filter(
        status=Task.STATUS_OPEN,
        deadline__isnull=False,
        deadline__lt=now,
    )
    ids = list(qs.values_list("pk", flat=True))
    if not ids:
        return 0
    n = Task.objects.filter(pk__in=ids).update(status=Task.STATUS_COMPLETED, updated_at=now)
    release_incomplete_applications_for_task_ids(ids)
    return n


def advance_virtual_application_counts(*, now=None) -> tuple[int, int]:
    """
    为开启自动增长的任务按整小时随机增加虚拟参与人数。

    返回 `(更新任务数, 新增虚拟人数总量)`。
    """
    current = now or timezone.now()
    tasks = (
        Task.objects.filter(
            status=Task.STATUS_OPEN,
            virtual_hourly_growth_max__gt=0,
        )
        .only(
            "id",
            "created_at",
            "updated_at",
            "virtual_hourly_growth_min",
            "virtual_hourly_growth_max",
            "virtual_growth_last_at",
        )
        .iterator(chunk_size=200)
    )
    touched = 0
    total_added = 0
    for task in tasks:
        min_growth = max(0, int(task.virtual_hourly_growth_min or 0))
        max_growth = max(0, int(task.virtual_hourly_growth_max or 0))
        if max_growth < min_growth:
            max_growth = min_growth
        if max_growth <= 0:
            continue

        anchor = task.virtual_growth_last_at or task.updated_at or task.created_at or current
        elapsed_hours = int(max(0, (current - anchor).total_seconds()) // 3600)
        if elapsed_hours <= 0:
            continue

        added = sum(random.randint(min_growth, max_growth) for _ in range(elapsed_hours))
        update_qs = Task.objects.filter(pk=task.pk)
        if task.virtual_growth_last_at is None:
            update_qs = update_qs.filter(virtual_growth_last_at__isnull=True)
        else:
            update_qs = update_qs.filter(virtual_growth_last_at=task.virtual_growth_last_at)

        update_kwargs = {"virtual_growth_last_at": current}
        if added > 0:
            update_kwargs["virtual_auto_increment_count"] = F("virtual_auto_increment_count") + added

        updated = update_qs.update(**update_kwargs)
        if updated:
            touched += 1
            total_added += added
    return touched, total_added


def _decimal_to_cents(value) -> int:
    amount = Decimal(value or "0")
    cents = (amount * Decimal("100")).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return max(0, int(cents))


def advance_virtual_platform_stats(*, now=None) -> dict[str, object]:
    """
    为首页统计按整小时随机增加虚拟展示值。

    返回：
    {
        "updated": bool,
        "elapsed_hours": int,
        "added_total_tasks": int,
        "added_total_rewards_usdt": Decimal,
        "added_total_users": int,
        "added_operating_days": int,
    }
    """
    current = now or timezone.now()
    config = PlatformStatsDisplayConfig.get()
    anchor = config.virtual_growth_last_at or config.updated_at or current
    elapsed_hours = int(max(0, (current - anchor).total_seconds()) // 3600)
    result: dict[str, object] = {
        "updated": False,
        "elapsed_hours": elapsed_hours,
        "added_total_tasks": 0,
        "added_total_rewards_usdt": Decimal("0.00"),
        "added_total_users": 0,
        "added_operating_days": 0,
    }
    if elapsed_hours <= 0:
        return result

    int_specs = (
        (
            "added_total_tasks",
            "total_tasks_hourly_growth_min",
            "total_tasks_hourly_growth_max",
            "total_tasks_virtual_auto_increment",
        ),
        (
            "added_total_users",
            "total_users_hourly_growth_min",
            "total_users_hourly_growth_max",
            "total_users_virtual_auto_increment",
        ),
        (
            "added_operating_days",
            "operating_days_hourly_growth_min",
            "operating_days_hourly_growth_max",
            "operating_days_virtual_auto_increment",
        ),
    )
    update_kwargs = {"virtual_growth_last_at": current}
    for result_key, min_field, max_field, auto_field in int_specs:
        min_growth = max(0, int(getattr(config, min_field, 0) or 0))
        max_growth = max(0, int(getattr(config, max_field, 0) or 0))
        if max_growth < min_growth:
            max_growth = min_growth
        added = sum(random.randint(min_growth, max_growth) for _ in range(elapsed_hours)) if max_growth > 0 else 0
        result[result_key] = added
        if added > 0:
            update_kwargs[auto_field] = F(auto_field) + added

    reward_min_cents = _decimal_to_cents(config.total_rewards_usdt_hourly_growth_min)
    reward_max_cents = _decimal_to_cents(config.total_rewards_usdt_hourly_growth_max)
    if reward_max_cents < reward_min_cents:
        reward_max_cents = reward_min_cents
    reward_added_cents = (
        sum(random.randint(reward_min_cents, reward_max_cents) for _ in range(elapsed_hours))
        if reward_max_cents > 0
        else 0
    )
    reward_added = (Decimal(reward_added_cents) / Decimal("100")).quantize(Decimal("0.01"))
    result["added_total_rewards_usdt"] = reward_added
    if reward_added_cents > 0:
        update_kwargs["total_rewards_usdt_virtual_auto_increment"] = (
            F("total_rewards_usdt_virtual_auto_increment") + reward_added
        )

    updated = PlatformStatsDisplayConfig.objects.filter(pk=config.pk).update(**update_kwargs)
    result["updated"] = bool(updated)
    return result
