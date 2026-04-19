"""任务与报名生命周期：接取人数、必做绑定特例、满员/到期收尾、待处理超时。"""

from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.db import DEFAULT_DB_ALIAS, connections, transaction
from django.utils import timezone

from .models import Task, TaskApplication


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


def active_taker_count(task: Task) -> int:
    """接取人数：待处理 + 已录用（每人至多一条报名）。"""
    return task.applications.filter(
        status__in=(TaskApplication.STATUS_PENDING, TaskApplication.STATUS_ACCEPTED)
    ).count()


def task_pending_can_expire(task: Task) -> bool:
    """是否适用「接取后须在超时内完成」。
    - 传统 interaction=none 悬赏：等发布人审核，不自动超时。
    - 必做账号绑定：多依赖站外操作，不自动超时（避免误杀进行中的绑定流程）。
    """
    if task.interaction_type == Task.INTERACTION_NONE:
        return False
    if is_mandatory_no_slot_cap(task):
        return False
    return True


def _pending_timeout_minutes() -> int:
    return max(1, int(getattr(settings, "TASK_PENDING_APPLICATION_TIMEOUT_MINUTES", 30)))


def maybe_mark_task_completed_when_slots_full(task_id: int) -> None:
    """普通任务：接取人数已满则任务标为已完成，不再接新单；已在席的待处理可继续完成。"""
    connections[DEFAULT_DB_ALIAS].close()
    with transaction.atomic():
        task = Task.objects.select_for_update().get(pk=task_id)
        if task.status != Task.STATUS_OPEN or is_mandatory_no_slot_cap(task):
            return
        if active_taker_count(task) < task.applicants_limit:
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
        if accepted < task.applicants_limit:
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
        created_at__lt=cutoff,
    ).select_related("task")
    n = 0
    for app in candidates.iterator(chunk_size=200):
        if not task_pending_can_expire(app.task):
            continue
        u = TaskApplication.objects.filter(pk=app.pk, status=TaskApplication.STATUS_PENDING).update(
            status=TaskApplication.STATUS_CANCELLED,
            decided_at=timezone.now(),
        )
        if u:
            n += 1
    return n


def close_tasks_past_deadline() -> int:
    """截止时间已过且仍为可报名的任务标记为已完成。"""
    now = timezone.now()
    return Task.objects.filter(
        status=Task.STATUS_OPEN,
        deadline__isnull=False,
        deadline__lt=now,
    ).update(status=Task.STATUS_COMPLETED, updated_at=now)
