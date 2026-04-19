"""按任务绑定平台规范化 bound_username（报名与校验共用）。"""

from __future__ import annotations

from .instagram_client import normalize_instagram_username
from .models import Task
from .tiktok_client import normalize_tiktok_username
from .twitter_client import normalize_twitter_username
from .youtube_client import normalize_youtube_channel_identifier


def normalize_bound_username_for_task(task: Task, raw: str | None) -> str:
    if not raw:
        return ""
    s = str(raw).strip()
    if not s:
        return ""
    if task.interaction_type != Task.INTERACTION_ACCOUNT_BINDING:
        return s.lstrip("@").strip()
    bp = task.binding_platform
    if bp == Task.BINDING_TWITTER:
        return normalize_twitter_username(s)
    if bp == Task.BINDING_TIKTOK:
        return normalize_tiktok_username(s)
    if bp == Task.BINDING_INSTAGRAM:
        return normalize_instagram_username(s)
    if bp == Task.BINDING_YOUTUBE:
        return normalize_youtube_channel_identifier(s) or ""
    return s.lstrip("@").strip()


def account_binding_requires_bound_username(task: Task) -> bool:
    return task.interaction_type == Task.INTERACTION_ACCOUNT_BINDING and task.binding_platform in (
        Task.BINDING_TWITTER,
        Task.BINDING_TIKTOK,
    )
