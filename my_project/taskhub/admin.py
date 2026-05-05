import logging

from django import forms
from django.contrib import admin, messages
from django.db import transaction
from django.db.utils import OperationalError, ProgrammingError
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone
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
    MembershipLevelConfig,
    OnlineFeedback,
    PlatformStatsDisplayConfig,
    ReferralRewardConfig,
    ScreenshotProofReview,
    Task,
    TaskApplication,
    TaskCategory,
    TaskCompletionRecord,
    TeamLeaderTier,
)
from .platform_publisher import get_task_platform_publisher, is_platform_publisher
from .task_lifecycle import after_publisher_accepts_application, effective_applicants_limit, is_mandatory_no_slot_cap
from .task_rewards import grant_task_completion_reward

logger = logging.getLogger(__name__)


def finalize_accepted_application(application: TaskApplication) -> dict:
    """后台审核通过后，补齐名额收尾与钱包奖励发放。奖励函数本身按 reward_paid_at 防重复。"""
    now = timezone.now()
    with transaction.atomic():
        app = TaskApplication.objects.select_for_update().select_related("task", "applicant").get(pk=application.pk)
        if app.status != TaskApplication.STATUS_ACCEPTED:
            app.status = TaskApplication.STATUS_ACCEPTED
            app.decided_at = now
            app.save(update_fields=["status", "decided_at", "updated_at"])
        elif not app.decided_at:
            app.decided_at = now
            app.save(update_fields=["decided_at", "updated_at"])

        task_ref = app.task
        if not is_mandatory_no_slot_cap(task_ref) and effective_applicants_limit(task_ref) == 1:
            TaskApplication.objects.filter(task=task_ref, status=TaskApplication.STATUS_PENDING).exclude(
                pk=app.pk
            ).update(status=TaskApplication.STATUS_REJECTED, decided_at=now)

    after_publisher_accepts_application(task_ref)

    with transaction.atomic():
        app = TaskApplication.objects.select_for_update().select_related("task", "applicant").get(pk=application.pk)
        if app.status != TaskApplication.STATUS_ACCEPTED:
            return {"granted": False, "reason": "not_accepted", "usdt": "0", "th_coin": "0"}
        return grant_task_completion_reward(app)


def reject_applications(queryset) -> int:
    now = timezone.now()
    return queryset.exclude(status=TaskApplication.STATUS_ACCEPTED).update(
        status=TaskApplication.STATUS_REJECTED,
        decided_at=now,
    )


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
        "is_vip_exclusive",
        "task_list_order",
        "virtual_application_display_count",
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
        "is_vip_exclusive",
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
    readonly_fields = (
        "interaction_config_guide",
        "virtual_application_display_count",
        "virtual_auto_increment_count",
        "virtual_growth_last_at",
    )

    @admin.display(description="发布", ordering="publisher_id")
    def release_source(self, obj):
        if is_platform_publisher(obj.publisher_id):
            return "平台"
        return obj.publisher.username if obj.publisher_id else "—"

    @admin.display(description="展示参与人数（虚拟）")
    def virtual_application_display_count(self, obj):
        return obj.display_virtual_application_count()

    def save_model(self, request, obj, form, change):
        obj.publisher = get_task_platform_publisher()
        super().save_model(request, obj, form, change)

    @admin.display(description="interaction_config 填什么（只读说明）")
    def interaction_config_guide(self, obj):
        return format_html(
            "<p>下面「交互配置 JSON」须为对象 <code>{{}}</code>。不配就留 <code>{{}}</code>（除「加入社群」外）。</p>"
            "<ul style='margin:8px 0 0 1.1em;line-height:1.65'>"
            "<li><strong>Twitter 绑定</strong>（要用户打开哪条推文、是否必须转发）：<br><code>{}</code></li>"
            "<li><strong>社交任务：关注 / 转发 / 点赞</strong>（Twitter / Instagram / TikTok）："
            "把「必做任务类型」设为<strong>关注</strong>、<strong>转发</strong>或<strong>点赞</strong>，"
            "再选「目标平台」。前台会先让用户打开目标链接，再点「我已完成」走 "
            "<code>verify-social-action</code>。示例：<br>"
            "Twitter 关注：<code>{}</code><br>"
            "Twitter 转发：<code>{}</code><br>"
            "Twitter 点赞：<code>{}</code><br>"
            "Instagram 关注：<code>{}</code><br>"
            "Instagram 点赞：<code>{}</code><br>"
            "TikTok 关注：<code>{}</code><br>"
            "TikTok 转发：<code>{}</code><br>"
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
            "<li><strong>上传截图审核</strong>：把「必做任务类型」设为<strong>上传截图审核</strong>；"
            "用户前台接任务后上传截图，后台在「任务报名」里查看凭证并审核通过/拒绝。"
            "可在 JSON 写目标链接或说明，前台会展示并让用户打开：<br><code>{}</code></li>"
            "</ul>",
            '{"target_tweet_url":"https://x.com/账号/status/推文ID","require_retweet":true,"require_follow":false,"target_follow_username":""}',
            '{"target_follow_username":"taskhub_official","target_profile_url":"https://x.com/taskhub_official"}',
            '{"target_tweet_url":"https://x.com/taskhub_official/status/1234567890"}',
            '{"target_tweet_url":"https://x.com/taskhub_official/status/1234567890","target_like_url":"https://x.com/taskhub_official/status/1234567890"}',
            '{"target_profile_url":"https://www.instagram.com/taskhub_official/"}',
            '{"target_post_url":"https://www.instagram.com/p/ABCDEF12345/"}',
            '{"target_profile_url":"https://www.tiktok.com/@taskhub_official"}',
            '{"target_video_url":"https://www.tiktok.com/@taskhub_official/video/1234567890123456789"}',
            '{"target_video_url":"https://www.tiktok.com/@taskhub_official/video/1234567890123456789"}',
            '{"youtube_proof_link":"https://你要用户粘贴的完整链接"}',
            '{"instagram_proof_link":"须填完整唯一链接（如 https://t.me/… 或活动落地页）；勿只填 https://www.instagram.com/ 根路径，易误匹配"}',
            '{"facebook_proof_link":"https://www.facebook.com/你的主页路径/…"}',
            '{"target_video_url":"https://www.tiktok.com/@官方号/video/数字ID","require_repost":true}',
            '{"invite_link":"https://t.me/+xxxx","telegram_chat_id":"-1001234567890"}',
            '{"target_url":"https://example.com/campaign","instructions":"完成页面要求后上传截图，等待后台审核"}',
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
                    "is_vip_exclusive",
                    "status",
                ),
                "description": (
                    "发布人保存时自动设为平台账号（<code>TASK_PLATFORM_PUBLISHER_ID</code>）。"
                    "<strong>首页必做列表</strong>（<code>GET /api/v1/tasks/mandatory/</code>）仅展示：勾选「首页必做」且<strong>状态为可报名</strong>的任务。"
                    "<br><strong>VIP 任务专区</strong>：勾选后任务会进入前台 VIP 专区，仅 VIP1 及以上会员可接，"
                    "并按“会员等级活动配置”里的每日上限限制领取。"
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
                    "virtual_application_count",
                    "virtual_hourly_growth_min",
                    "virtual_hourly_growth_max",
                    "virtual_application_display_count",
                    "virtual_auto_increment_count",
                    "virtual_growth_last_at",
                ),
                "description": (
                    "<strong>需求人数（applicants_limit）</strong>：可录用名额；默认曾为 1，仅 1 人录用后普通任务即可能关单，"
                    "入群/必做等多人均可参与时请<strong>调大</strong>。"
                    "<br><strong>截止时间</strong>：留空则不按到期自动关单；到期后 cron "
                    "<code>python manage.py maintain_tasks</code> 会把仍「可报名」的任务标为已完成并释放未完成报名。"
                    "<br><strong>必做排序（task_list_order）</strong>：数值越大越靠前（与接口一致）。"
                    "<br><strong>虚拟参与人数（virtual_application_count）</strong>：基础虚拟人数。"
                    "<br><strong>每小时虚拟增长最小/最大值</strong>：配置后，现有 cron "
                    "<code>python manage.py maintain_tasks</code> 会每小时随机累加一次，范围取两者之间。"
                    "<br><strong>展示参与人数（虚拟）</strong>：基础虚拟人数 + 自动增长累计人数；仅影响前台列表显示，不影响名额、进度、录用与发奖。"
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
    actions = ("approve_selected_applications", "reject_selected_applications", "unbind_selected_binding_accounts")
    search_fields = (
        "task__title",
        "applicant__username",
        "applicant__phone",
        "applicant__invite_code",
    )
    raw_id_fields = ("task", "applicant")
    readonly_fields = ("proof_image_preview", "reward_paid_at", "created_at", "updated_at")
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
        ("完成与凭证", {"fields": ("bound_username", "proof_image", "proof_image_preview", "self_verified_at", "reward_paid_at")}),
        ("系统", {"fields": ("created_at", "updated_at")}),
    )

    @admin.display(description="有截图", boolean=True)
    def has_proof(self, obj):
        return bool(obj.proof_image)

    @admin.display(description="截图预览")
    def proof_image_preview(self, obj):
        if not obj.proof_image:
            return "—"
        try:
            url = obj.proof_image.url
        except Exception:
            return "截图文件不可访问"
        return format_html(
            '<a href="{}" target="_blank" rel="noopener">'
            '<img src="{}" style="max-width:360px;max-height:260px;border-radius:10px;border:1px solid #e5e7eb;" />'
            "</a>",
            url,
            url,
        )

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

    def save_model(self, request, obj, form, change):
        old = None
        if change and obj.pk:
            old = TaskApplication.objects.filter(pk=obj.pk).values("status", "reward_paid_at").first()
        if obj.status in {TaskApplication.STATUS_REJECTED, TaskApplication.STATUS_CANCELLED} and not obj.decided_at:
            obj.decided_at = timezone.now()
        super().save_model(request, obj, form, change)
        should_finalize = obj.status == TaskApplication.STATUS_ACCEPTED and (
            old is None or old.get("status") != TaskApplication.STATUS_ACCEPTED or not old.get("reward_paid_at")
        )
        if should_finalize:
            try:
                result = finalize_accepted_application(obj)
            except OperationalError as exc:
                self.message_user(request, f"审核通过已保存，但奖励发放失败：{exc}", level=messages.ERROR)
                return
            if result.get("granted"):
                self.message_user(
                    request,
                    f"已审核通过并发放奖励：USDT {result.get('usdt')} / TH {result.get('th_coin')}",
                    level=messages.SUCCESS,
                )
            elif result.get("reason") == "already_paid":
                self.message_user(request, "已审核通过；该报名奖励此前已发放，未重复发放。", level=messages.INFO)
            elif result.get("reason") == "no_reward_configured":
                self.message_user(request, "已审核通过；该任务未配置奖励金额，钱包无变动。", level=messages.WARNING)

    @admin.action(description="审核通过并发放任务奖励")
    def approve_selected_applications(self, request, queryset):
        ok = 0
        failed = 0
        granted_usdt = []
        granted_th = []
        for app in queryset.select_related("task", "applicant"):
            try:
                result = finalize_accepted_application(app)
                ok += 1
                if result.get("granted"):
                    granted_usdt.append(str(result.get("usdt", "0")))
                    granted_th.append(str(result.get("th_coin", "0")))
            except OperationalError:
                failed += 1
        msg = f"已审核通过 {ok} 条"
        if granted_usdt or granted_th:
            msg += "，并按任务配置发放奖励"
        if failed:
            self.message_user(request, f"{msg}；{failed} 条因系统繁忙失败，请稍后重试。", level=messages.ERROR)
        else:
            self.message_user(request, msg, level=messages.SUCCESS)

    @admin.action(description="审核拒绝所选报名")
    def reject_selected_applications(self, request, queryset):
        count = reject_applications(queryset)
        self.message_user(request, f"已拒绝 {count} 条报名。", level=messages.SUCCESS)

    @admin.action(description="解绑所选账号绑定记录")
    def unbind_selected_binding_accounts(self, request, queryset):
        count = queryset.filter(
            task__interaction_type=Task.INTERACTION_ACCOUNT_BINDING,
        ).exclude(status=TaskApplication.STATUS_CANCELLED).update(
            status=TaskApplication.STATUS_CANCELLED,
            bound_username=None,
            self_verified_at=None,
            decided_at=timezone.now(),
        )
        self.message_user(request, f"已解绑 {count} 条账号绑定记录。")


@admin.register(ScreenshotProofReview)
class ScreenshotProofReviewAdmin(TaskApplicationAdmin):
    """集中处理前台上传截图后的待审核任务。"""

    list_display = (
        "id",
        "proof_thumb",
        "task_admin_link",
        "applicant",
        "status",
        "self_verified_at",
        "created_at",
        "decided_at",
        "reward_paid_at",
    )
    list_display_links = ("id", "proof_thumb")
    list_filter = ("status", "self_verified_at", "created_at", "decided_at", "reward_paid_at")
    actions = ("approve_selected_applications", "reject_selected_applications")
    readonly_fields = (
        "task",
        "applicant",
        "proof_image",
        "proof_image_preview",
        "self_verified_at",
        "reward_paid_at",
        "created_at",
        "updated_at",
    )
    fieldsets = (
        ("审核对象", {"fields": ("task", "applicant", "status", "decided_at")}),
        ("用户上传截图", {"fields": ("proof_image", "proof_image_preview", "self_verified_at")}),
        ("奖励与备注", {"fields": ("reward_paid_at", "proposal", "quoted_price")}),
        ("系统", {"fields": ("created_at", "updated_at")}),
    )

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .filter(
                task__verification_mode=Task.VERIFY_SCREENSHOT,
                status=TaskApplication.STATUS_PENDING,
                proof_image__isnull=False,
            )
            .exclude(proof_image="")
        )

    def has_add_permission(self, request):
        return False

    @admin.display(description="截图")
    def proof_thumb(self, obj):
        if not obj.proof_image:
            return "—"
        try:
            url = obj.proof_image.url
        except Exception:
            return "不可访问"
        return format_html(
            '<a href="{}" target="_blank" rel="noopener">'
            '<img src="{}" style="width:72px;height:72px;object-fit:cover;border-radius:8px;border:1px solid #e5e7eb;" />'
            "</a>",
            url,
            url,
        )

    @admin.display(description="任务")
    def task_admin_link(self, obj):
        if not obj.task_id:
            return "—"
        url = reverse("admin:taskhub_task_change", args=[obj.task_id])
        return format_html('<a href="{}" target="_blank" rel="noopener">{}</a>', url, obj.task.title)


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
    actions = ("unbind_selected_binding_accounts",)
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

    @admin.action(description="解绑所选账号绑定记录")
    def unbind_selected_binding_accounts(self, request, queryset):
        count = queryset.filter(
            task__interaction_type=Task.INTERACTION_ACCOUNT_BINDING,
        ).update(
            status=TaskApplication.STATUS_CANCELLED,
            bound_username=None,
            self_verified_at=None,
            decided_at=timezone.now(),
        )
        self.message_user(request, f"已解绑 {count} 条账号绑定记录。")


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
    list_display = (
        "id",
        "direct_invite_rate",
        "second_task_rate",
        "direct_recharge_rate",
        "second_recharge_rate",
        "updated_at",
    )
    fieldsets = (
        (
            "活动展示文案",
            {
                "fields": ("activity_title", "activity_intro"),
                "description": "前台/机器人可直接展示这里的活动标题和简介。",
            },
        ),
        (
            "任务分成",
            {
                "fields": ("direct_invite_rate", "second_task_rate"),
                "description": (
                    "下级完成任务并实际到账 <strong>USDT 任务奖励</strong> 后，"
                    "系统按一级/二级比例自动给上级发放「推荐奖励」。例如 <code>0.20</code> 表示 20%。"
                ),
            },
        ),
        (
            "会员开通返利",
            {
                "fields": ("direct_recharge_rate", "second_recharge_rate"),
                "description": (
                    "这里沿用原来的两项比例字段，但语义已改为<strong>会员开通返利</strong>："
                    "下级购买会员后，一级/二级上级按比例获得返利。"
                    "返利基数会按上级自身会员等级的加入费用进行<strong>烧伤封顶</strong>。"
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


@admin.register(PlatformStatsDisplayConfig)
class PlatformStatsDisplayConfigAdmin(TolerantDjangoAdminLogMixin, admin.ModelAdmin):
    list_display = ("id", "updated_at", "virtual_growth_last_at")
    fieldsets = (
        (
            "说明",
            {
                "fields": (),
                "description": (
                    "这里可以修改首页排行榜顶部 <strong>4 个统计项</strong> 的展示值：任务总数、总发放奖励、总用户数、运营天数。"
                    "<br>前台展示值 = <strong>真实统计</strong> + <strong>虚拟基础值</strong> + <strong>自动增长累计值</strong>。"
                    "<br>自动增长累计值由计划任务 <code>python manage.py maintain_platform_stats</code> 按整小时随机累加。"
                    "<br><strong>在线人数不在这里配置</strong>，它会按最近活跃用户实时统计。"
                ),
            },
        ),
        (
            "任务总数",
            {
                "fields": (
                    "total_tasks_virtual_base",
                    "total_tasks_hourly_growth_min",
                    "total_tasks_hourly_growth_max",
                    "total_tasks_virtual_auto_increment",
                )
            },
        ),
        (
            "总发放奖励（USDT）",
            {
                "fields": (
                    "total_rewards_usdt_virtual_base",
                    "total_rewards_usdt_hourly_growth_min",
                    "total_rewards_usdt_hourly_growth_max",
                    "total_rewards_usdt_virtual_auto_increment",
                )
            },
        ),
        (
            "总用户数",
            {
                "fields": (
                    "total_users_virtual_base",
                    "total_users_hourly_growth_min",
                    "total_users_hourly_growth_max",
                    "total_users_virtual_auto_increment",
                )
            },
        ),
        (
            "运营天数",
            {
                "fields": (
                    "operating_days_virtual_base",
                    "operating_days_hourly_growth_min",
                    "operating_days_hourly_growth_max",
                    "operating_days_virtual_auto_increment",
                )
            },
        ),
        ("系统", {"fields": ("virtual_growth_last_at", "updated_at")}),
    )
    readonly_fields = (
        "total_tasks_virtual_auto_increment",
        "total_rewards_usdt_virtual_auto_increment",
        "total_users_virtual_auto_increment",
        "operating_days_virtual_auto_increment",
        "virtual_growth_last_at",
        "updated_at",
    )

    def has_add_permission(self, request):
        try:
            return not PlatformStatsDisplayConfig.objects.exists()
        except ProgrammingError:
            return False

    def changelist_view(self, request, extra_context=None):
        try:
            obj = PlatformStatsDisplayConfig.get()
        except ProgrammingError:
            messages.error(request, "请先执行：python manage.py migrate")
            return redirect(reverse("admin:index"))
        return redirect(reverse("admin:taskhub_platformstatsdisplayconfig_change", args=[obj.pk]))

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(MembershipLevelConfig)
class MembershipLevelConfigAdmin(TolerantDjangoAdminLogMixin, admin.ModelAdmin):
    list_display = (
        "id",
        "sort_order",
        "level",
        "name",
        "join_fee_usdt",
        "daily_official_task_limit",
        "withdraw_fee_rate",
        "can_claim_free_tasks",
        "can_claim_official_tasks",
        "can_claim_high_commission_tasks",
        "unlimited_tasks",
        "is_active",
    )
    list_filter = (
        "is_active",
        "can_claim_free_tasks",
        "can_claim_official_tasks",
        "can_claim_high_commission_tasks",
        "unlimited_tasks",
    )
    search_fields = ("name", "description")
    ordering = ("sort_order", "level")
    fieldsets = (
        (
            "等级基础",
            {
                "fields": ("sort_order", "level", "name", "join_fee_usdt", "is_active"),
                "description": "等级数值要与会员表中的 membership_level 对应，例如 VIP0 填 0，VIP1 填 1。",
            },
        ),
        (
            "任务权限",
            {
                "fields": (
                    "can_claim_free_tasks",
                    "can_claim_official_tasks",
                    "can_claim_high_commission_tasks",
                    "daily_official_task_limit",
                    "unlimited_tasks",
                ),
                "description": "VIP 任务专区每日上限留空表示不限量；VIP1 可填 1，VIP2 可填 2，VIP3 勾选不限量。",
            },
        ),
        ("提现手续费", {"fields": ("withdraw_fee_rate",), "description": "按提现金额比例扣除；0.20 表示 20%，0 表示免手续费。"}),
        ("说明", {"fields": ("description",)}),
        ("系统", {"fields": ("created_at", "updated_at")}),
    )
    readonly_fields = ("created_at", "updated_at")


@admin.register(TeamLeaderTier)
class TeamLeaderTierAdmin(TolerantDjangoAdminLogMixin, admin.ModelAdmin):
    list_display = (
        "id",
        "sort_order",
        "name",
        "direct_vip_count",
        "target_period",
        "team_recharge_target_usdt",
        "team_performance_rate",
        "is_active",
    )
    list_filter = ("is_active", "target_period")
    search_fields = ("name", "description")
    ordering = ("sort_order", "id")
    fieldsets = (
        (
            "门槛",
            {
                "fields": ("sort_order", "name", "direct_vip_count", "team_recharge_target_usdt", "target_period", "is_active"),
                "description": "用于配置团队长/超级代理扶持政策，如直推 VIP 人数和团队充值业绩目标。",
            },
        ),
        ("提成", {"fields": ("team_performance_rate",), "description": "0.02 表示团队业绩额外提成 2%。"}),
        ("说明", {"fields": ("description",)}),
        ("系统", {"fields": ("created_at", "updated_at")}),
    )
    readonly_fields = ("created_at", "updated_at")


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
                "description": "API v2 只读 Bearer；当前主要用于点赞校验与旧版兼容回退。留空则使用环境变量或 <code>core/twitter_secrets.py</code>。",
            },
        ),
        (
            "Apify（Instagram / Twitter / TikTok）",
            {
                "fields": (
                    "apify_api_token",
                    "apify_instagram_actor_id",
                    "apify_instagram_timeout_sec",
                    "apify_twitter_follow_actor_id",
                    "apify_twitter_repost_actor_id",
                    "apify_twitter_timeout_sec",
                    "apify_twitter_following_max_results",
                    "apify_twitter_auth_token",
                    "apify_twitter_ct0",
                    "apify_tiktok_actor_id",
                    "apify_tiktok_timeout_sec",
                    "apify_tiktok_results_per_page",
                ),
                "description": (
                    "共用同一 Apify Token；Twitter 关注默认走 <code>automation-lab/twitter-scraper</code>（following 模式），"
                    "Twitter 转发默认走 <code>api-ninja/x-twitter-replies-retweets-scraper</code>。"
                    "其中关注校验建议额外填写 <code>auth_token</code> / <code>ct0</code>，以提升稳定性。"
                    "Actor 与超时等留空则回退 <code>core/settings.py</code> / <code>core/apify_secrets.py</code>。"
                ),
            },
        ),
        ("系统", {"fields": ("updated_at",)}),
    )
    readonly_fields = ("updated_at",)

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        if db_field.name in (
            "telegram_bot_token",
            "twitter_bearer_token",
            "apify_api_token",
            "apify_twitter_auth_token",
            "apify_twitter_ct0",
        ):
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


@admin.register(OnlineFeedback)
class OnlineFeedbackAdmin(TolerantDjangoAdminLogMixin, admin.ModelAdmin):
    list_display = ("id", "user", "title", "status", "created_at", "replied_at")
    list_filter = ("status", "created_at", "replied_at")
    search_fields = ("user__username", "user__phone", "user__telegram_id", "title", "content", "admin_reply")
    raw_id_fields = ("user",)
    readonly_fields = ("created_at", "updated_at", "replied_at")
    ordering = ("-updated_at", "-id")
    fieldsets = (
        ("用户反馈", {"fields": ("user", "title", "content", "contact", "status")}),
        ("后台回复", {"fields": ("admin_reply", "replied_by", "replied_at")}),
        ("系统", {"fields": ("created_at", "updated_at")}),
    )

    def save_model(self, request, obj, form, change):
        if obj.admin_reply.strip() and not obj.replied_by:
            obj.replied_by = getattr(request.user, "username", "") or "admin"
        super().save_model(request, obj, form, change)

    def has_module_permission(self, request):
        return bool(request.user and request.user.is_active and request.user.is_staff)

    def has_view_permission(self, request, obj=None):
        return bool(request.user and request.user.is_active and request.user.is_staff)

    def has_change_permission(self, request, obj=None):
        return bool(request.user and request.user.is_active and request.user.is_staff)

    def has_add_permission(self, request):
        return bool(request.user and request.user.is_active and request.user.is_staff)


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
