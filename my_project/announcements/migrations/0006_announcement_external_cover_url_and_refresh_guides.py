from __future__ import annotations

import json
import math
from pathlib import Path

from django.db import migrations, models
from django.db.models import Q
from django.utils.dateparse import parse_datetime
from django.utils.html import strip_tags
from django.utils.timezone import is_naive, make_aware, now


SEED_FILE = Path(__file__).resolve().parents[1] / "seed" / "foxigrow_guides.json"
POST_NEWBIE = "newbie_guide"
GUIDE_ARTICLE = "article"


def _load_seed() -> list[dict]:
    return json.loads(SEED_FILE.read_text(encoding="utf-8"))


def _read_minutes(html: str) -> int:
    plain = strip_tags(html or "").strip()
    if not plain:
        return 3
    return max(1, min(30, math.ceil(len(plain) / 450)))


def _coerce_publish_at(raw: str | None):
    dt = parse_datetime(str(raw or "").strip())
    if not dt:
        return now()
    if is_naive(dt):
        return make_aware(dt)
    return dt


def _get_or_create_category(GuideCategory, *, slug: str, name: str, sort_order: int):
    category = (
        GuideCategory.objects.filter(Q(slug__iexact=slug) | Q(name__iexact=name))
        .order_by("id")
        .first()
    )
    if category is None:
        return GuideCategory.objects.create(
            slug=slug,
            name=name,
            sort_order=sort_order,
            is_active=True,
        )

    changed = False
    if category.slug != slug:
        category.slug = slug
        changed = True
    if category.name != name:
        category.name = name
        changed = True
    if category.sort_order != sort_order:
        category.sort_order = sort_order
        changed = True
    if not category.is_active:
        category.is_active = True
        changed = True
    if changed:
        category.save(update_fields=["slug", "name", "sort_order", "is_active"])
    return category


def forwards(apps, schema_editor):
    Announcement = apps.get_model("announcements", "Announcement")
    GuideCategory = apps.get_model("announcements", "GuideCategory")

    for item in _load_seed():
        category = _get_or_create_category(
            GuideCategory,
            slug=item["category_slug"],
            name=item["category_name"],
            sort_order=int(item.get("category_sort_order") or 0),
        )
        defaults = {
            "post_type": POST_NEWBIE,
            "title": item["title"],
            "content": item["content_html"],
            "excerpt": item.get("excerpt") or "",
            "guide_type": item.get("guide_type") or GUIDE_ARTICLE,
            "external_cover_url": item.get("cover_image") or "",
            "video_url": item.get("video_url") or "",
            "duration_display": "",
            "read_minutes": _read_minutes(item.get("content_html") or ""),
            "is_featured": bool(item.get("is_featured")),
            "guide_category": category,
            "category_key": "",
            "category_label": "",
            "author_name": "TaskHub 官方教程",
            "is_active": True,
            "publish_at": _coerce_publish_at(item.get("published_at")),
            "expire_at": None,
        }
        guide = Announcement.objects.filter(slug=item["slug"]).first()
        if guide is None:
            Announcement.objects.create(slug=item["slug"], **defaults)
            continue
        for field, value in defaults.items():
            setattr(guide, field, value)
        guide.save(update_fields=list(defaults.keys()))


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("announcements", "0005_import_foxigrow_guides"),
    ]

    operations = [
        migrations.AddField(
            model_name="announcement",
            name="external_cover_url",
            field=models.URLField(
                blank=True,
                db_comment="未上传本地封面时可填写外链；前台优先本地图片，其次此外链",
                default="",
                max_length=500,
                verbose_name="封面外链",
            ),
        ),
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
