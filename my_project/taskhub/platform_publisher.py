"""平台发布任务时使用的前台用户（FrontendUser）。"""

from __future__ import annotations

from django.conf import settings

from users.models import FrontendUser


def get_task_platform_publisher() -> FrontendUser:
    """返回配置的平台发布人；未配置或用户不存在则抛异常。"""
    pid = getattr(settings, "TASK_PLATFORM_PUBLISHER_ID", None)
    if pid is None:
        raise ValueError("未配置 TASK_PLATFORM_PUBLISHER_ID（前台用户主键）")
    return FrontendUser.objects.get(pk=int(pid))


def is_platform_publisher(user_id: int | None) -> bool:
    if user_id is None:
        return False
    pid = getattr(settings, "TASK_PLATFORM_PUBLISHER_ID", None)
    if pid is None:
        return False
    return int(user_id) == int(pid)
