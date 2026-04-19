"""新手指南公开 API：数据来自 Announcement（post_type=newbie_guide），路径仍为 /api/v1/guides/。"""

from __future__ import annotations

from django.db.models import F, Q
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from taskhub.api_views import api_error, api_response, parse_positive_int

from .models import Announcement, GuideCategory


def _newbie_qs():
    now = timezone.now()
    return Announcement.objects.filter(
        post_type=Announcement.POST_NEWBIE,
        is_active=True,
        publish_at__lte=now,
    ).filter(Q(expire_at__isnull=True) | Q(expire_at__gte=now)).select_related("guide_category")


def _cover_url(request, a: Announcement):
    if not a.cover:
        return None
    try:
        return request.build_absolute_uri(a.cover.url)
    except Exception:
        return a.cover.url


def _video_url(request, a: Announcement):
    if a.video_file:
        try:
            return request.build_absolute_uri(a.video_file.url)
        except Exception:
            return a.video_file.url
    if a.video_url:
        return a.video_url
    return None


def _category_dict(a: Announcement):
    if a.guide_category_id and a.guide_category:
        gc = a.guide_category
        return {"id": gc.id, "name": gc.name, "slug": gc.slug}
    if a.category_key:
        return {
            "id": hash(a.category_key) % (10**9),
            "name": a.category_label or a.category_key,
            "slug": a.category_key,
        }
    return None


def _serialize_list(request, a: Announcement):
    return {
        "id": a.id,
        "title": a.title,
        "slug": a.slug or None,
        "excerpt": a.excerpt or None,
        "guide_type": a.guide_type,
        "cover_url": _cover_url(request, a),
        "video_url": _video_url(request, a),
        "duration_display": a.duration_display or None,
        "read_minutes": a.read_minutes,
        "view_count": a.view_count,
        "is_featured": a.is_featured,
        "author_name": a.author_name,
        "published_at": a.publish_at.isoformat() if a.publish_at else None,
        "category": _category_dict(a),
    }


def _serialize_detail(request, a: Announcement):
    d = _serialize_list(request, a)
    d["body"] = a.content
    return d


@csrf_exempt
@require_http_methods(["GET"])
def guide_categories_api(request):
    items = [{"id": 0, "name": "全部指南", "slug": "", "sort_order": 10**9}]
    seen_slugs = {""}
    for gc in GuideCategory.objects.filter(is_active=True).order_by("sort_order", "id"):
        items.append(
            {
                "id": gc.id,
                "name": gc.name,
                "slug": gc.slug,
                "sort_order": gc.sort_order,
            }
        )
        seen_slugs.add(gc.slug)
    # 仅手写旧字段、尚未挂 FK 的指南，仍出现在 Tab（slug 与后台分类不重复时才追加）
    legacy_map = {}
    for row in (
        _newbie_qs()
        .filter(guide_category_id__isnull=True)
        .exclude(category_key="")
        .values("category_key", "category_label")
        .iterator()
    ):
        k = row["category_key"]
        if k and k not in legacy_map:
            legacy_map[k] = (row["category_label"] or "").strip() or k
    fake_id = 10**6
    for slug in sorted(legacy_map.keys()):
        if slug in seen_slugs:
            continue
        fake_id += 1
        seen_slugs.add(slug)
        items.append(
            {
                "id": fake_id,
                "name": legacy_map[slug],
                "slug": slug,
                "sort_order": 50000,
            }
        )
    return api_response({"items": items})


@csrf_exempt
@require_http_methods(["GET"])
def guide_featured_api(request):
    qs = _newbie_qs()
    g = qs.filter(is_featured=True).order_by("-publish_at", "-id").first()
    if g is None:
        g = qs.filter(guide_type=Announcement.GUIDE_VIDEO).order_by("-publish_at", "-id").first()
    if g is None:
        g = qs.order_by("-publish_at", "-id").first()
    if g is None:
        return api_response({"item": None})
    return api_response({"item": _serialize_list(request, g)})


@csrf_exempt
@require_http_methods(["GET"])
def guide_list_api(request):
    qs = _newbie_qs()

    cat_slug = (request.GET.get("category_slug") or "").strip()
    if cat_slug:
        qs = qs.filter(Q(guide_category__slug=cat_slug) | Q(category_key=cat_slug))

    gt = (request.GET.get("guide_type") or "").strip()
    if gt in {Announcement.GUIDE_ARTICLE, Announcement.GUIDE_VIDEO}:
        qs = qs.filter(guide_type=gt)

    search = (request.GET.get("search") or "").strip()
    if search:
        qs = qs.filter(Q(title__icontains=search) | Q(excerpt__icontains=search) | Q(content__icontains=search))

    ex = (request.GET.get("exclude_featured") or "1").strip().lower()
    if ex in ("1", "true", "yes"):
        qs = qs.filter(is_featured=False)

    try:
        page = parse_positive_int(request.GET.get("page", 1), "page")
        page_size = parse_positive_int(request.GET.get("page_size", 20), "page_size")
    except ValueError as exc:
        return api_error(str(exc), code=5001, status=400)
    page_size = min(page_size, 50)

    total = qs.count()
    offset = (page - 1) * page_size
    items = list(qs.order_by("-is_featured", "-publish_at", "-id")[offset : offset + page_size])

    return api_response(
        {
            "items": [_serialize_list(request, a) for a in items],
            "pagination": {"page": page, "page_size": page_size, "total": total},
        }
    )


@csrf_exempt
@require_http_methods(["GET"])
def guide_detail_api(request, pk: int):
    try:
        a = _newbie_qs().get(pk=pk)
    except Announcement.DoesNotExist:
        return api_error("指南不存在或未发布", code=5002, status=404)

    Announcement.objects.filter(pk=a.pk).update(view_count=F("view_count") + 1)
    a.refresh_from_db(fields=["view_count"])

    return api_response({"guide": _serialize_detail(request, a)})
