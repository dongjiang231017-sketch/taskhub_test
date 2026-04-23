from __future__ import annotations

from django.db.models import QuerySet

from .models import AgentProfile, FrontendUser


def get_agent_profile_for_request(request):
    if not getattr(request, "user", None) or not request.user.is_authenticated:
        return None
    if hasattr(request, "_agent_profile_cache"):
        return request._agent_profile_cache
    try:
        profile = AgentProfile.objects.select_related("root_user", "backend_user").get(
            backend_user=request.user,
            is_active=True,
        )
    except AgentProfile.DoesNotExist:
        profile = None
    request._agent_profile_cache = profile
    return profile


def collect_descendant_user_ids(root_user_id: int, include_self: bool = True) -> set[int]:
    visible_ids: set[int] = {root_user_id} if include_self else set()
    seen_ids: set[int] = {root_user_id}
    frontier = [root_user_id]

    while frontier:
        children = list(
            FrontendUser.objects.filter(referrer_id__in=frontier).values_list("id", flat=True)
        )
        frontier = [user_id for user_id in children if user_id not in seen_ids]
        seen_ids.update(frontier)
        visible_ids.update(frontier)

    return visible_ids


def get_agent_visible_user_ids(request) -> set[int] | None:
    """
    Return None for superusers so admin pages can remain useful for inspection.
    Normal agents receive the configured root user and every recursive child.
    """

    if getattr(request.user, "is_superuser", False):
        return None
    if hasattr(request, "_agent_visible_user_ids_cache"):
        return request._agent_visible_user_ids_cache

    profile = get_agent_profile_for_request(request)
    if profile is None:
        request._agent_visible_user_ids_cache = set()
        return request._agent_visible_user_ids_cache

    request._agent_visible_user_ids_cache = collect_descendant_user_ids(
        profile.root_user_id,
        include_self=profile.include_self,
    )
    return request._agent_visible_user_ids_cache


def filter_queryset_by_agent_users(request, queryset: QuerySet, user_lookup: str) -> QuerySet:
    visible_ids = get_agent_visible_user_ids(request)
    if visible_ids is None:
        return queryset
    if not visible_ids:
        return queryset.none()
    return queryset.filter(**{f"{user_lookup}__in": visible_ids})


def count_agent_visible_users(request) -> int:
    visible_ids = get_agent_visible_user_ids(request)
    if visible_ids is None:
        return FrontendUser.objects.count()
    return len(visible_ids)


def describe_agent_scope(request) -> str:
    profile = get_agent_profile_for_request(request)
    if profile is None:
        return "全部数据" if getattr(request.user, "is_superuser", False) else "未开通代理权限"
    total = count_agent_visible_users(request)
    root = profile.root_user
    return f"{root.username} (#{root.id}) 伞下 {total} 人"
