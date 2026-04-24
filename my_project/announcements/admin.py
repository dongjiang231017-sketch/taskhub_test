from django import forms
from django.contrib import admin

from .models import Announcement, GuideCategory


@admin.register(GuideCategory)
class GuideCategoryAdmin(admin.ModelAdmin):
    list_display = ("id", "slug", "name", "sort_order", "is_active")
    list_filter = ("is_active",)
    search_fields = ("slug", "name")
    ordering = ("sort_order", "slug")

_DATETIME_FMT = "%Y-%m-%d %H:%M"
_DATETIME_INPUT_FORMATS = ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f")


class AnnouncementAdminForm(forms.ModelForm):
    """发布时间 / 失效时间使用 Flatpickr 单框选择，替代 Admin 默认拆分的日期+时间。"""

    publish_at = forms.DateTimeField(
        label="发布时间",
        required=True,
        input_formats=_DATETIME_INPUT_FORMATS,
        widget=forms.DateTimeInput(
            format=_DATETIME_FMT,
            attrs={
                "class": "announcements-dtp vTextField",
                "autocomplete": "off",
                "placeholder": "选择日期与时间",
            },
        ),
    )
    expire_at = forms.DateTimeField(
        label="失效时间",
        required=False,
        input_formats=_DATETIME_INPUT_FORMATS,
        widget=forms.DateTimeInput(
            format=_DATETIME_FMT,
            attrs={
                "class": "announcements-dtp vTextField",
                "autocomplete": "off",
                "placeholder": "可选，留空表示不过期",
            },
        ),
    )

    class Meta:
        model = Announcement
        fields = "__all__"
        widgets = {
            "excerpt": forms.Textarea(attrs={"rows": 3, "cols": 80}),
        }


@admin.register(Announcement)
class AnnouncementAdmin(admin.ModelAdmin):
    form = AnnouncementAdminForm
    list_display = (
        "id",
        "title",
        "post_type",
        "guide_type",
        "guide_category",
        "is_featured",
        "is_active",
        "publish_at",
        "expire_at",
        "view_count",
    )
    list_filter = ("post_type", "guide_type", "guide_category", "is_featured", "is_active", "publish_at")
    search_fields = ("title", "excerpt", "content", "category_key", "slug", "guide_category__name", "guide_category__slug")
    autocomplete_fields = ("guide_category",)
    readonly_fields = ("created_at", "view_count")
    prepopulated_fields = {"slug": ("title",)}
    fieldsets = (
        (
            "类型与状态",
            {
                "fields": ("post_type", "is_active", "is_featured", "publish_at", "expire_at"),
                "description": "选「新手指南」后填写下方指南专用字段；系统公告可留空指南字段。",
            },
        ),
        (
            "通用",
            {
                "fields": ("title", "slug", "cover", "external_cover_url", "author_name"),
                "description": "封面优先使用本地上传；未上传时前台会回退到「封面外链」。",
            },
        ),
        (
            "新手指南专用",
            {
                "fields": (
                    "excerpt",
                    "guide_type",
                    "guide_category",
                    "video_file",
                    "video_url",
                    "duration_display",
                    "read_minutes",
                ),
                "description": "分类：请先在「新手指南 → 指南分类」里新建 Tab，再在此处搜索选择。视频：可上传文件或填写外链；均填写时前台优先使用上传文件。",
            },
        ),
        (
            "旧版分类手写字段（仅兼容历史数据）",
            {
                "classes": ("collapse",),
                "fields": ("category_key", "category_label"),
            },
        ),
        ("正文（富文本）", {"fields": ("content",)}),
        ("统计", {"fields": ("view_count", "created_at")}),
    )

    class Media:
        css = {
            "all": (
                "https://cdn.jsdelivr.net/npm/flatpickr/dist/flatpickr.min.css",
                "announcements/css/admin-datetime.css",
            ),
        }
        js = (
            "https://cdn.jsdelivr.net/npm/tinymce@6/tinymce.min.js",
            "announcements/js/tinymce-init.js",
            "https://cdn.jsdelivr.net/npm/flatpickr/dist/flatpickr.min.js",
            "https://cdn.jsdelivr.net/npm/flatpickr/dist/l10n/zh.js",
            "announcements/js/admin-datetime.js",
        )
