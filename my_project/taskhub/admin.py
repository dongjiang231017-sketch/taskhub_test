import logging

from django import forms
from django.contrib import admin, messages
from django.db.utils import OperationalError, ProgrammingError
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.html import format_html

from users.admin_widgets import binding_modal_trigger

from .models import (
    ApiToken,
    CheckInConfig,
    CheckInRecord,
    DailyTaskDayClaim,
    DailyTaskDefinition,
    IntegrationSecretConfig,
    InviteAchievementClaim,
    InviteAchievementTier,
    ReferralRewardConfig,
    Task,
    TaskApplication,
    TaskCategory,
    TaskCompletionRecord,
)
from .platform_publisher import get_task_platform_publisher, is_platform_publisher

logger = logging.getLogger(__name__)


class TolerantDjangoAdminLogMixin:
    """
    MySQL 开启 GTID 时，若 django_admin_log（等）为 MyISAM 而业务表为 InnoDB，
    在同一事务里写操作日志会触发 OperationalError 1785。此处吞掉该错误以免后台整页 500；
    根治请在库里执行：ALTER TABLE django_admin_log ENGINE=InnoDB;（以及 django_session 等）。
    """

    def _skip_gtid_mixed_engine(self, exc):
        return isinstance(exc, OperationalError) and exc.args and exc.args[0] == 1785

    def log_addition(self, request, object, message):
        try:
            return super().log_addition(request, object, message)
        except OperationalError as e:
            if self._skip_gtid_mixed_engine(e):
                logger.warning("已跳过 admin 新增日志（MySQL 1785），请把 django_admin_log 改为 InnoDB: %s", e)
                return
            raise

    def log_change(self, request, object, message):
        try:
            return super().log_change(request, object, message)
        except OperationalError as e:
            if self._skip_gtid_mixed_engine(e):
                logger.warning("已跳过 admin 修改日志（MySQL 1785）: %s", e)
                return
            raise

    def log_deletion(self, request, object, object_repr):
        try:
            return super().log_deletion(request, object, object_repr)
        except OperationalError as e:
            if self._skip_gtid_mixed_engine(e):
                logger.warning("已跳过 admin 删除日志（MySQL 1785）: %s", e)
                return
            raise


@admin.register(TaskCategory)
class TaskCategoryAdmin(TolerantDjangoAdminLogMixin, admin.ModelAdmin):
    list_display = ("id", "name", "slug", "sort_order", "is_active", "created_at")
    list_filter = ("is_active",)
    search_fields = ("name", "slug")
    ordering = ("-sort_order", "id")


@admin.register(Task)
class TaskAdmin(TolerantDjangoAdminLogMixin, admin.ModelAdmin):
    # publisher 保存时由 save_model 写入平台账号；verification_mode 由模型 save/clean 按类型推导
    exclude = ("publisher", "verification_mode")
    list_display = (
        "id",
        "title",
        "is_mandatory",
        "task_list_order",
        "interaction_type",
        "binding_platform",
        "reward_usdt",
        "reward_th_coin",
        "release_source",
        "category",
        "budget",
        "status",
        "deadline",
        "created_at",
    )
    list_filter = (
        "status",
        "category",
        "is_mandatory",
        "interaction_type",
        "binding_platform",
        "created_at",
    )
    search_fields = (
        "title",
        "description",
        "publisher__username",
        "publisher__phone",
        "publisher__invite_code",
    )
    autocomplete_fields = ("category",)
    readonly_fields = ("interaction_config_guide",)

    @admin.display(description="发布", ordering="publisher_id")
    def release_source(self, obj):
        if is_platform_publisher(obj.publisher_id):
            return "平台"
        return obj.publisher.username if obj.publisher_id else "—"

    def save_model(self, request, obj, form, change):
        obj.publisher = get_task_platform_publisher()
        super().save_model(request, obj, form, change)

    @admin.display(description="interaction_config 填什么（只读说明）")
    def interaction_config_guide(self, obj):
        return format_html(
            "<p>下面「交互配置 JSON」须为对象 <code>{{}}</code>。不配就留 <code>{{}}</code>（除「加入社群」外）。</p>"
            "<ul style='margin:8px 0 0 1.1em;line-height:1.65'>"
            "<li><strong>Twitter 绑定</strong>（要用户打开哪条推文、是否必须转发）：<br><code>{}</code></li>"
            "<li><strong>社交任务：关注 / 点赞</strong>（Twitter / Instagram / TikTok）："
            "把「必做任务类型」设为<strong>关注</strong>或<strong>点赞</strong>，"
            "再选「目标平台」。前台会先让用户打开目标链接，再点「我已完成」走 "
            "<code>verify-social-action</code>。示例：<br>"
            "Twitter 关注：<code>{}</code><br>"
            "Twitter 点赞：<code>{}</code><br>"
            "Instagram 关注：<code>{}</code><br>"
            "Instagram 点赞：<code>{}</code><br>"
            "TikTok 关注：<code>{}</code><br>"
            "TikTok 点赞：<code>{}</code></li>"
            "<li><strong>YouTube 等简介留链</strong>（用户简介里必须出现的一段 URL；键名须为 <code>youtube_proof_link</code>，"
            "接口会额外返回 <code>binding_reference_url</code> 供前端「复制链接」）：<br><code>{}</code></li>"
            "<li><strong>Instagram / Facebook 绑定</strong>（与 YouTube 同属「简介/外链留链证明」；"
            "<strong>Instagram</strong> 留链校验<strong>仅</strong>走 Apify，须在服务器配置 <code>APIFY_API_TOKEN</code>）。"
            "「必做任务类型」选<strong>账号绑定</strong>后，「绑定平台」选 Instagram / Facebook；"
            "键名示例：<br>"
            "Instagram：<code>{}</code><br>"
            "Facebook：<code>{}</code></li>"
            "<li><strong>TikTok 绑定（转发指定视频 + 用户名校验）</strong>：与推特类似，走 "
            "<code>POST …/verify-tiktok/</code>；须在服务器配置 <code>APIFY_API_TOKEN</code>，"
            "默认使用 Apify Actor <code>clockworks/tiktok-scraper</code> 抓取用户 Reposts。"
            "<code>binding_reference_url</code> 会取 <code>target_video_url</code>（或 <code>tiktok_video_url</code>）。示例：<br>"
            "<code>{}</code></li>"
            "<li><strong>加入 Telegram 群 / 社群</strong>：<strong>必填</strong> <code>invite_link</code> 或 <code>telegram_invite_link</code>；"
            "若要在用户报名后<strong>自动校验已入群</strong>，再加 <code>telegram_chat_id</code>（群或超级群 id，如 <code>-100…</code>），"
            "并将与本站 Mini App 使用的 Bot 拉进群且给予<strong>拉人/读成员</strong>权限；接口字段 <code>interaction_verify_action</code> 会为 "
            "<code>verify-telegram-group</code>，用户须已用 Telegram 登录。示例：<br><code>{}</code></li>"
            "<li><strong>看视频/投票</strong>：详细规则写「任务描述」；截图在「任务报名」里上传。可选：<br><code>{}</code></li>"
            "</ul>",
            '{"target_tweet_url":"https://x.com/账号/status/推文ID","require_retweet":true,"require_follow":false,"target_follow_username":""}',
            '{"target_follow_username":"taskhub_official","target_profile_url":"https://x.com/taskhub_official"}',
            '{"target_tweet_url":"https://x.com/taskhub_official/status/1234567890","target_like_url":"https://x.com/taskhub_official/status/1234567890"}',
            '{"target_profile_url":"https://www.instagram.com/taskhub_official/"}',
            '{"target_post_url":"https://www.instagram.com/p/ABCDEF12345/"}',
            '{"target_profile_url":"https://www.tiktok.com/@taskhub_official"}',
            '{"target_video_url":"https://www.tiktok.com/@taskhub_official/video/1234567890123456789"}',
            '{"youtube_proof_link":"https://你要用户粘贴的完整链接"}',
            '{"instagram_proof_link":"须填完整唯一链接（如 https://t.me/… 或活动落地页）；勿只填 https://www.instagram.com/ 根路径，易误匹配"}',
            '{"facebook_proof_link":"https://www.facebook.com/你的主页路径/…"}',
            '{"target_video_url":"https://www.tiktok.com/@官方号/video/数字ID","require_repost":true}',
            '{"invite_link":"https://t.me/+xxxx","telegram_chat_id":"-1001234567890"}',
            '{"min_watch_seconds":30}',
        )

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        if db_field.name == "interaction_config":
            kwargs.setdefault(
                "widget",
                forms.Textarea(attrs={"rows": 10, "cols": 86, "style": "font-family:monospace;font-size:12px"}),
            )
        return super().formfield_for_dbfield(db_field, request, **kwargs)

    fieldsets = (
        (
            "任务与状态",
            {
                "fields": (
                    "category",
                    "title",
                    "description",
                    "is_mandatory",
                    "status",
                ),
                "description": (
                    "发布人保存时自动设为平台账号（<code>TASK_PLATFORM_PUBLISHER_ID</code>）。"
                    "<strong>首页必做列表</strong>（<code>GET /api/v1/tasks/mandatory/</code>）仅展示：勾选「首页必做」且<strong>状态为可报名</strong>的任务。"
                    "<br><strong>任务分类</strong>请在上方选择，便于后续按类筛选与展示。"
                    "<strong>需求人数、截止时间、必做排序</strong>等在「名额与截止」分组填写；"
                    "普通任务录用人数达到需求人数且非「不按名额关单」玩法时，系统可能将任务标为<strong>已完成</strong>。"
                    "预算与卡片展示奖励见「预算与展示奖励」分组。"
                ),
            },
        ),
        (
            "名额与截止",
            {
                "fields": (
                    "applicants_limit",
                    "deadline",
                    "task_list_order",
                ),
                "description": (
                    "<strong>需求人数（applicants_limit）</strong>：可录用名额；默认曾为 1，仅 1 人录用后普通任务即可能关单，"
                    "入群/必做等多人均可参与时请<strong>调大</strong>。"
                    "<br><strong>截止时间</strong>：留空则不按到期自动关单；到期后 cron "
                    "<code>python manage.py maintain_tasks</code> 会把仍「可报名」的任务标为已完成并释放未完成报名。"
                    "<br><strong>必做排序（task_list_order）</strong>：数值越大越靠前（与接口一致）。"
                ),
            },
        ),
        (
            "预算与展示奖励",
            {
                "fields": (
                    "budget",
                    "reward_unit",
                    "reward_usdt",
                    "reward_th_coin",
                ),
                "description": (
                    "<strong>预算金额</strong>与<strong>币种</strong>为任务预算口径；"
                    "<strong>展示奖励 USDT / TH</strong>为任务卡片上展示的奖励文案数值（可与预算独立）。"
                    "不需要的奖励字段可留空。"
                ),
            },
        ),
        (
            "玩法与 JSON 配置",
            {
                "fields": (
                    "interaction_config_guide",
                    "interaction_type",
                    "binding_platform",
                    "interaction_config",
                ),
                "description": (
                    "先看上方只读说明再改 JSON。<strong>校验方式</strong>随类型自动带出，无需在后台手选。"
                    "<br>账号绑定类须选绑定平台；非账号绑定时保存会清空平台。"
                    "YouTube / Instagram / Facebook 简介留链、TikTok 转发视频、Telegram 入群等示例见上表。"
                ),
            },
        ),
    )


@admin.register(TaskApplication)
class TaskApplicationAdmin(TolerantDjangoAdminLogMixin, admin.ModelAdmin):
    class Media:
        css = {
            "all": (
                "users/admin_changelist_members.css",
                "users/admin_binding_modal.css",
            )
        }
        js = ("users/admin_binding_modal.js",)

    list_display = (
        "id",
        "task",
        "applicant",
        "bound_username_preview",
        "has_proof",
        "quoted_price",
        "status",
        "self_verified_at",
        "created_at",
        "decided_at",
    )
    list_filter = ("status", "created_at")
    search_fields = (
        "task__title",
        "applicant__username",
        "applicant__phone",
        "applicant__invite_code",
    )
    raw_id_fields = ("task", "applicant")
    readonly_fields = ("created_at", "updated_at")
    fieldsets = (
        ("任务与用户", {"fields": ("task", "applicant")}),
        (
            "报名内容（悬赏/报价，可选）",
            {
                "classes": ("collapse",),
                "fields": ("proposal", "quoted_price", "status", "decided_at"),
                "description": "纯必做任务可不看；有人接单报价时才用。",
            },
        ),
        ("完成与凭证", {"fields": ("bound_username", "proof_image", "self_verified_at")}),
        ("系统", {"fields": ("created_at", "updated_at")}),
    )

    @admin.display(description="有截图", boolean=True)
    def has_proof(self, obj):
        return bool(obj.proof_image)

    @admin.display(description="绑定账号")
    def bound_username_preview(self, obj):
        bu = (obj.bound_username or "").strip()
        if not bu:
            return "—"
        task = obj.task
        plat = ""
        if task.interaction_type == Task.INTERACTION_ACCOUNT_BINDING and task.binding_platform:
            plat = task.get_binding_platform_display()
        rows = [{"platform": plat or "报名", "account": bu}]
        return binding_modal_trigger(rows, label="已绑定 · 查看")


@admin.register(TaskCompletionRecord)
class TaskCompletionRecordAdmin(TolerantDjangoAdminLogMixin, admin.ModelAdmin):
    """仅展示已录用（视为任务完成）的报名；与「任务报名」同表，勿重复录入。"""

    class Media:
        css = {
            "all": (
                "users/admin_changelist_members.css",
                "users/admin_binding_modal.css",
            )
        }
        js = ("users/admin_binding_modal.js",)

    list_display = (
        "id",
        "task",
        "applicant",
        "bound_username_preview",
        "reward_paid_at",
        "self_verified_at",
        "decided_at",
        "created_at",
    )
    list_filter = ("decided_at", "created_at", "reward_paid_at")
    search_fields = (
        "task__title",
        "applicant__username",
        "applicant__phone",
        "applicant__invite_code",
    )
    raw_id_fields = ("task", "applicant")
    readonly_fields = ("created_at", "updated_at")
    fieldsets = (
        ("任务与用户", {"fields": ("task", "applicant")}),
        (
            "完成与奖励",
            {
                "fields": (
                    "status",
                    "bound_username",
                    "self_verified_at",
                    "decided_at",
                    "reward_paid_at",
                    "proof_image",
                ),
            },
        ),
        (
            "其它",
            {
                "classes": ("collapse",),
                "fields": ("proposal", "quoted_price"),
            },
        ),
        ("系统", {"fields": ("created_at", "updated_at")}),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).filter(status=TaskApplication.STATUS_ACCEPTED)

    def has_add_permission(self, request):
        return False

    def save_model(self, request, obj, form, change):
        obj.status = TaskApplication.STATUS_ACCEPTED
        super().save_model(request, obj, form, change)

    @admin.display(description="绑定账号")
    def bound_username_preview(self, obj):
        bu = (obj.bound_username or "").strip()
        if not bu:
            return "—"
        task = obj.task
        plat = ""
        if task.interaction_type == Task.INTERACTION_ACCOUNT_BINDING and task.binding_platform:
            plat = task.get_binding_platform_display()
        rows = [{"platform": plat or "报名", "account": bu}]
        return binding_modal_trigger(rows, label="已绑定 · 查看")


@admin.register(CheckInConfig)
class CheckInConfigAdmin(TolerantDjangoAdminLogMixin, admin.ModelAdmin):
    list_display = (
        "id",
        "daily_reward_usdt",
        "daily_reward_th_coin",
        "makeup_cost_th_coin",
        "weekly_makeup_limit",
        "updated_at",
    )
    fieldsets = (
        (
            "奖励与消耗",
            {
                "fields": ("daily_reward_usdt", "daily_reward_th_coin", "makeup_cost_th_coin"),
                "description": "正常签到与补签成功后，均按上两项增加 USDT / TH Coin；补签另按「补签消耗」从 TH Coin 扣除（先扣后发奖）。均为 0 表示该档不发放或不消耗。",
            },
        ),
        ("次数", {"fields": ("weekly_makeup_limit",)}),
        ("系统", {"fields": ("updated_at",)}),
    )
    readonly_fields = ("updated_at",)

    def has_add_permission(self, request):
        return not CheckInConfig.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ReferralRewardConfig)
class ReferralRewardConfigAdmin(TolerantDjangoAdminLogMixin, admin.ModelAdmin):
    list_display = ("id", "direct_invite_rate", "updated_at")
    fieldsets = (
        (
            "返佣规则",
            {
                "fields": ("direct_invite_rate",),
                "description": (
                    "下级完成任务并实际到账 <strong>USDT 任务奖励</strong> 后，"
                    "系统按此比例自动给上级发放「推荐奖励」。例如 <code>0.10</code> 表示 10%。"
                ),
            },
        ),
        ("系统", {"fields": ("updated_at",)}),
    )
    readonly_fields = ("updated_at",)

    def has_add_permission(self, request):
        try:
            return not ReferralRewardConfig.objects.exists()
        except ProgrammingError:
            return False

    def changelist_view(self, request, extra_context=None):
        try:
            obj = ReferralRewardConfig.get()
        except ProgrammingError:
            messages.error(request, "请先执行：python manage.py migrate")
            return redirect(reverse("admin:index"))
        return redirect(reverse("admin:taskhub_referralrewardconfig_change", args=[obj.pk]))

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(IntegrationSecretConfig)
class IntegrationSecretConfigAdmin(TolerantDjangoAdminLogMixin, admin.ModelAdmin):
    list_display = ("id", "updated_at")
    fieldsets = (
        (
            "Telegram",
            {
                "fields": ("telegram_bot_token",),
                "description": (
                    "与 Mini App 登录、入群校验 <code>getChatMember</code> 使用同一 Bot。"
                    "此处留空则仍使用环境变量 <code>TELEGRAM_BOT_TOKEN</code> 或 <code>core/telegram_secrets.py</code>。"
                ),
            },
        ),
        (
            "Twitter / X",
            {
                "fields": ("twitter_bearer_token",),
                "description": "API v2 只读 Bearer；留空则使用环境变量或 <code>core/twitter_secrets.py</code>。",
            },
        ),
        (
            "Apify（Instagram / TikTok）",
            {
                "fields": (
                    "apify_api_token",
                    "apify_instagram_actor_id",
                    "apify_instagram_timeout_sec",
                    "apify_tiktok_actor_id",
                    "apify_tiktok_timeout_sec",
                    "apify_tiktok_results_per_page",
                ),
                "description": (
                    "共用同一 Apify Token；Actor 与超时等留空则回退 <code>core/settings.py</code> / <code>core/apify_secrets.py</code>。"
                ),
            },
        ),
        ("系统", {"fields": ("updated_at",)}),
    )
    readonly_fields = ("updated_at",)

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        if db_field.name in ("telegram_bot_token", "twitter_bearer_token", "apify_api_token"):
            kwargs.setdefault(
                "widget",
                forms.Textarea(attrs={"rows": 4, "cols": 86, "style": "font-family:monospace;font-size:12px"}),
            )
        return super().formfield_for_dbfield(db_field, request, **kwargs)

    def has_add_permission(self, request):
        try:
            return not IntegrationSecretConfig.objects.exists()
        except ProgrammingError:
            return False

    def changelist_view(self, request, extra_context=None):
        """单例配置：列表地址直接进入编辑页，无需先点进列表再改。"""
        try:
            obj = IntegrationSecretConfig.get()
        except ProgrammingError:
            messages.error(
                request,
                "「第三方集成密钥」数据表尚未创建。请在项目根目录执行：python manage.py migrate（会创建 task_integration_secret_config 表）。",
            )
            return redirect(reverse("admin:index"))
        return redirect(
            reverse("admin:taskhub_integrationsecretconfig_change", args=[obj.pk])
        )

    def change_view(self, request, object_id, form_url="", extra_context=None):
        try:
            return super().change_view(request, object_id, form_url, extra_context=extra_context)
        except ProgrammingError:
            messages.error(
                request,
                "「第三方集成密钥」数据表尚未创建。请执行：python manage.py migrate 后再试。",
            )
            return redirect(reverse("admin:index"))

    def add_view(self, request, form_url="", extra_context=None):
        try:
            return super().add_view(request, form_url, extra_context)
        except ProgrammingError:
            messages.error(request, "请先执行：python manage.py migrate")
            return redirect(reverse("admin:index"))

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(CheckInRecord)
class CheckInRecordAdmin(TolerantDjangoAdminLogMixin, admin.ModelAdmin):
    list_display = ("id", "user", "on_date", "is_make_up", "created_at")
    list_filter = ("is_make_up", "on_date")
    search_fields = ("user__username", "user__phone", "user__invite_code")
    raw_id_fields = ("user",)
    readonly_fields = ("created_at",)


@admin.register(DailyTaskDefinition)
class DailyTaskDefinitionAdmin(TolerantDjangoAdminLogMixin, admin.ModelAdmin):
    list_display = (
        "id",
        "sort_order",
        "title",
        "metric_code",
        "target_count",
        "reward_usdt",
        "reward_th",
        "is_active",
        "updated_at",
    )
    list_filter = ("is_active", "metric_code")
    ordering = ("sort_order", "id")
    fieldsets = (
        (
            "展示与条件",
            {
                "fields": ("sort_order", "title", "metric_code", "target_count", "is_active"),
                "description": (
                    "「当日完成任务数」口径：报名已录用且视为已完结的任务中，"
                    "完结日落在<strong>当日自然日</strong>的条数（与任务中心「已发奖」或无展示奖励的录用一致）。"
                ),
            },
        ),
        ("奖励", {"fields": ("reward_usdt", "reward_th")}),
        ("系统", {"fields": ("created_at", "updated_at")}),
    )
    readonly_fields = ("created_at", "updated_at")


@admin.register(DailyTaskDayClaim)
class DailyTaskDayClaimAdmin(TolerantDjangoAdminLogMixin, admin.ModelAdmin):
    list_display = ("id", "user", "definition", "on_date", "claimed_at")
    list_filter = ("on_date", "definition")
    search_fields = ("user__username", "user__phone", "user__invite_code")
    raw_id_fields = ("user",)
    readonly_fields = ("claimed_at",)
    ordering = ("-on_date", "-id")


@admin.register(ApiToken)
class ApiTokenAdmin(TolerantDjangoAdminLogMixin, admin.ModelAdmin):
    list_display = ("id", "user", "key", "created_at", "last_used_at")
    search_fields = ("user__username", "user__phone", "key")
    readonly_fields = ("key", "created_at", "last_used_at")


@admin.register(InviteAchievementTier)
class InviteAchievementTierAdmin(TolerantDjangoAdminLogMixin, admin.ModelAdmin):
    list_display = (
        "id",
        "sort_order",
        "title",
        "invite_threshold",
        "reward_usdt",
        "reward_th",
        "is_active",
        "updated_at",
    )
    list_filter = ("is_active",)
    ordering = ("sort_order", "invite_threshold", "id")
    fieldsets = (
        (
            "展示与条件",
            {
                "fields": ("sort_order", "title", "invite_threshold", "is_active"),
                "description": "有效邀请人数 = 直邀下级中账号启用（status=true）的人数，与邀请榜统计一致。",
            },
        ),
        ("奖励", {"fields": ("reward_usdt", "reward_th")}),
        ("系统", {"fields": ("created_at", "updated_at")}),
    )
    readonly_fields = ("created_at", "updated_at")


@admin.register(InviteAchievementClaim)
class InviteAchievementClaimAdmin(TolerantDjangoAdminLogMixin, admin.ModelAdmin):
    list_display = ("id", "user", "tier", "claimed_at")
    list_filter = ("tier", "claimed_at")
    search_fields = ("user__username", "user__phone", "user__invite_code")
    raw_id_fields = ("user",)
    readonly_fields = ("claimed_at",)
    ordering = ("-claimed_at",)
