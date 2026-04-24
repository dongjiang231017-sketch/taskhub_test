from django.core.validators import FileExtensionValidator
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class GuideCategory(models.Model):
    """新手指南 Tab 分类：在后台单独维护，指南条目通过外键选用。"""

    slug = models.SlugField(
        max_length=64,
        unique=True,
        verbose_name=_("分类标识"),
        db_comment="英文短横线，用于接口 category_slug 与前台 Tab",
    )
    name = models.CharField(max_length=64, verbose_name=_("展示名称"), db_comment="Tab 上显示的中文名")
    sort_order = models.PositiveSmallIntegerField(
        default=0,
        verbose_name=_("排序"),
        db_comment="数字越小越靠前",
    )
    is_active = models.BooleanField(default=True, verbose_name=_("是否启用"))

    class Meta:
        ordering = ("sort_order", "slug")
        verbose_name = _("新手指南分类")
        verbose_name_plural = _("新手指南分类")

    def __str__(self):
        return f"{self.name} ({self.slug})"


class Announcement(models.Model):
    POST_ANNOUNCEMENT = "announcement"
    POST_NEWBIE = "newbie_guide"
    POST_TYPE_CHOICES = (
        (POST_ANNOUNCEMENT, _("系统公告")),
        (POST_NEWBIE, _("新手指南")),
    )

    GUIDE_ARTICLE = "article"
    GUIDE_VIDEO = "video"
    GUIDE_TYPE_CHOICES = (
        (GUIDE_ARTICLE, _("图文")),
        (GUIDE_VIDEO, _("视频")),
    )

    post_type = models.CharField(
        max_length=32,
        choices=POST_TYPE_CHOICES,
        default=POST_ANNOUNCEMENT,
        verbose_name=_("内容类型"),
        db_comment="系统公告走原有展示；新手指南走 /api/v1/guides/ 与富文本编辑器",
    )
    title = models.CharField(max_length=255, verbose_name=_("标题"), db_comment="公告或指南标题")
    content = models.TextField(verbose_name=_("正文"), db_comment="富文本 HTML，新手指南详情同源")
    cover = models.ImageField(
        upload_to="announcements/",
        blank=True,
        null=True,
        verbose_name=_("封面图片"),
        db_comment="指南列表卡片图；可为空",
    )
    external_cover_url = models.URLField(
        max_length=500,
        blank=True,
        default="",
        verbose_name=_("封面外链"),
        db_comment="未上传本地封面时可填写外链；前台优先本地图片，其次此外链",
    )
    excerpt = models.CharField(
        max_length=500,
        blank=True,
        default="",
        verbose_name=_("摘要"),
        db_comment="新手指南列表副标题，可选",
    )
    slug = models.SlugField(
        max_length=120,
        blank=True,
        default="",
        verbose_name=_("URL 标识"),
        db_comment="可选，便于分享链接",
    )
    guide_type = models.CharField(
        max_length=20,
        choices=GUIDE_TYPE_CHOICES,
        default=GUIDE_ARTICLE,
        verbose_name=_("指南形态"),
        db_comment="仅新手指南有意义：图文或视频",
    )
    video_file = models.FileField(
        upload_to="announcements/videos/",
        blank=True,
        null=True,
        verbose_name=_("视频文件"),
        db_comment="本地上传；与外链二选一即可，均填写时前台优先用本地上传",
        validators=[
            FileExtensionValidator(
                allowed_extensions=("mp4", "webm", "mov", "m4v", "ogv", "mkv"),
            )
        ],
    )
    video_url = models.URLField(
        max_length=500,
        blank=True,
        default="",
        verbose_name=_("视频外链"),
        db_comment="guide_type=video 时可选：YouTube 等外链；无本地上传时使用",
    )
    duration_display = models.CharField(
        max_length=20,
        blank=True,
        default="",
        verbose_name=_("时长展示"),
        db_comment="如 12:45",
    )
    read_minutes = models.PositiveSmallIntegerField(
        default=4,
        verbose_name=_("阅读分钟"),
        db_comment="约读时间展示",
    )
    view_count = models.PositiveIntegerField(
        default=0,
        verbose_name=_("浏览量"),
        db_comment="指南详情接口访问时自增",
    )
    is_featured = models.BooleanField(
        default=False,
        verbose_name=_("置顶推荐"),
        db_comment="新手指南首页大卡，建议仅一条为 True",
    )
    guide_category = models.ForeignKey(
        GuideCategory,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="announcements",
        verbose_name=_("指南分类"),
        db_comment="在「新手指南分类」中维护；选后前台 Tab 与筛选用该分类",
    )
    category_key = models.CharField(
        max_length=64,
        blank=True,
        default="",
        db_index=True,
        verbose_name=_("指南分类标识（旧版）"),
        db_comment="已废弃：请改用上方「指南分类」；仅兼容历史数据",
    )
    category_label = models.CharField(
        max_length=64,
        blank=True,
        default="",
        verbose_name=_("指南分类展示名（旧版）"),
        db_comment="已废弃：请改用「新手指南分类」",
    )
    author_name = models.CharField(
        max_length=100,
        default="官方团队",
        verbose_name=_("作者展示名"),
        db_comment="详情页作者栏",
    )
    is_active = models.BooleanField(default=True, verbose_name=_("是否生效"), db_comment="公告是否对外生效")
    publish_at = models.DateTimeField(default=timezone.now, verbose_name=_("发布时间"), db_comment="公告发布时间")
    expire_at = models.DateTimeField(blank=True, null=True, verbose_name=_("失效时间"), db_comment="公告失效时间，可为空")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_("创建时间"), db_comment="公告创建时间")

    def __str__(self):
        return self.title

    class Meta:
        verbose_name = _("公告与指南")
        verbose_name_plural = verbose_name
        ordering = ("-publish_at",)
