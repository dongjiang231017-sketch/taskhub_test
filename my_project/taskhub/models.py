import secrets
from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone

from users.models import FrontendUser


class TaskCategory(models.Model):
    name = models.CharField(max_length=50, unique=True, verbose_name="分类名称", db_comment="任务分类名称")
    slug = models.SlugField(max_length=60, unique=True, verbose_name="分类标识", db_comment="任务分类唯一标识")
    description = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        verbose_name="分类描述",
        db_comment="分类简介",
    )
    sort_order = models.IntegerField(default=0, verbose_name="排序权重", db_comment="数值越大越靠前")
    is_active = models.BooleanField(default=True, verbose_name="是否启用", db_comment="前台是否展示")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间", db_comment="分类创建时间")

    class Meta:
        db_table = "task_category"
        verbose_name = "任务分类"
        verbose_name_plural = verbose_name
        ordering = ("-sort_order", "name")

    def __str__(self):
        return self.name


class Task(models.Model):
    STATUS_DRAFT = "draft"
    STATUS_OPEN = "open"
    STATUS_IN_PROGRESS = "in_progress"
    STATUS_COMPLETED = "completed"
    STATUS_CLOSED = "closed"
    STATUS_CHOICES = (
        (STATUS_DRAFT, "草稿"),
        (STATUS_OPEN, "可报名"),
        (STATUS_IN_PROGRESS, "进行中"),
        (STATUS_COMPLETED, "已完成"),
        (STATUS_CLOSED, "已关闭"),
    )

    # —— 必做任务：交互类型（与分类独立，按单条任务配置）——
    INTERACTION_NONE = "none"
    INTERACTION_ACCOUNT_BINDING = "account_binding"
    INTERACTION_FOLLOW = "follow"
    INTERACTION_COMMENT = "comment"
    INTERACTION_WATCH_VIDEO = "watch_video"
    INTERACTION_EXTERNAL_VOTE = "external_vote"
    INTERACTION_JOIN_COMMUNITY = "join_community"
    INTERACTION_CHOICES = (
        (INTERACTION_NONE, "无（不按下面规则校验）"),
        (INTERACTION_ACCOUNT_BINDING, "账号绑定（首页「绑定 Twitter/TikTok…」卡片）"),
        (INTERACTION_JOIN_COMMUNITY, "加入社群（如 Telegram 入群/频道）"),
        (INTERACTION_FOLLOW, "关注"),
        (INTERACTION_COMMENT, "评论"),
        (INTERACTION_WATCH_VIDEO, "观看视频"),
        (INTERACTION_EXTERNAL_VOTE, "外部网页投票"),
    )

    BINDING_PLATFORM_NONE = ""
    BINDING_TWITTER = "twitter"
    BINDING_YOUTUBE = "youtube"
    BINDING_INSTAGRAM = "instagram"
    BINDING_TIKTOK = "tiktok"
    BINDING_FACEBOOK = "facebook"
    BINDING_TELEGRAM = "telegram"
    BINDING_PLATFORM_CHOICES = (
        (BINDING_PLATFORM_NONE, "—"),
        (BINDING_TWITTER, "Twitter / X"),
        (BINDING_YOUTUBE, "YouTube"),
        (BINDING_INSTAGRAM, "Instagram"),
        (BINDING_TIKTOK, "TikTok"),
        (BINDING_FACEBOOK, "Facebook"),
        (BINDING_TELEGRAM, "Telegram"),
    )

    # 校验方式：推特绑定=填用户名+（可选）转发后用户点完成；YouTube=简介留指定链接；关注/评论=用户点完成；看视频/投票=截图审核
    VERIFY_USER_SELF = "user_self_confirm"
    VERIFY_PROFILE_LINK = "profile_link_proof"
    VERIFY_SCREENSHOT = "screenshot_review"
    VERIFY_CHOICES = (
        (VERIFY_USER_SELF, "用户自行确认完成"),
        (VERIFY_PROFILE_LINK, "简介/频道留指定链接证明"),
        (VERIFY_SCREENSHOT, "上传截图待审核"),
    )

    category = models.ForeignKey(
        TaskCategory,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tasks",
        verbose_name="任务分类",
        db_comment="任务所属分类",
    )
    publisher = models.ForeignKey(
        FrontendUser,
        on_delete=models.CASCADE,
        related_name="published_tasks",
        verbose_name="发布人",
        db_comment="任务发布用户ID",
    )
    title = models.CharField(max_length=200, verbose_name="任务标题", db_comment="任务标题")
    description = models.TextField(verbose_name="任务描述", db_comment="任务详情")
    budget = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
        verbose_name="预算金额",
        db_comment="任务预算金额",
    )
    reward_unit = models.CharField(max_length=12, default="CNY", verbose_name="币种", db_comment="预算币种")
    deadline = models.DateTimeField(blank=True, null=True, verbose_name="截止时间", db_comment="任务报名或完成截止时间")
    region = models.CharField(max_length=120, blank=True, null=True, verbose_name="任务地区", db_comment="任务执行地区")
    applicants_limit = models.PositiveIntegerField(default=1, verbose_name="需求人数", db_comment="任务可录用人数")
    contact_name = models.CharField(max_length=50, blank=True, null=True, verbose_name="联系人", db_comment="联系姓名")
    contact_phone = models.CharField(max_length=30, blank=True, null=True, verbose_name="联系电话", db_comment="联系方式")
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_OPEN,
        verbose_name="任务状态",
        db_comment="任务当前状态",
    )
    interaction_type = models.CharField(
        max_length=32,
        choices=INTERACTION_CHOICES,
        default=INTERACTION_NONE,
        verbose_name="必做任务类型",
        db_comment="账号绑定/关注/评论/看视频/外站投票等",
    )
    binding_platform = models.CharField(
        max_length=20,
        choices=BINDING_PLATFORM_CHOICES,
        default=BINDING_PLATFORM_NONE,
        blank=True,
        verbose_name="绑定平台",
        db_comment="仅当必做类型为账号绑定时使用",
    )
    verification_mode = models.CharField(
        max_length=32,
        choices=VERIFY_CHOICES,
        blank=True,
        null=True,
        verbose_name="校验方式",
        db_comment="由业务推导，也可在后台手动改",
    )
    interaction_config = models.JSONField(
        default=dict,
        blank=True,
        verbose_name="交互配置 JSON",
        db_comment="如 target_tweet_url、require_retweet、youtube_proof_link、invite_link 等",
    )
    is_mandatory = models.BooleanField(
        default=False,
        verbose_name="首页显示「必做」角标",
        db_comment="对应 TaskFlow 卡片右上角红色必做丝带",
    )
    task_list_order = models.PositiveIntegerField(
        default=0,
        verbose_name="首页列表排序权重",
        db_comment="数值越大越靠前，用于必做任务区排序",
    )
    reward_usdt = models.DecimalField(
        max_digits=12,
        decimal_places=4,
        blank=True,
        null=True,
        validators=[MinValueValidator(Decimal("0"))],
        verbose_name="展示奖励 USDT",
        db_comment="卡片上 +0.05 USDT 等，可与 budget 独立",
    )
    reward_th_coin = models.DecimalField(
        max_digits=20,
        decimal_places=2,
        blank=True,
        null=True,
        validators=[MinValueValidator(Decimal("0"))],
        verbose_name="展示奖励 TH",
        db_comment="卡片上 +2 TH 等",
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间", db_comment="任务创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间", db_comment="任务更新时间")

    class Meta:
        db_table = "task_job"
        verbose_name = "任务（发布单 / 首页必做卡片）"
        verbose_name_plural = verbose_name
        ordering = ("-task_list_order", "-created_at")

    def __str__(self):
        return f"{self.title} ({self.get_status_display()})"

    def clean(self):
        from django.core.exceptions import ValidationError

        super().clean()
        if self.interaction_type == self.INTERACTION_ACCOUNT_BINDING and not self.binding_platform:
            raise ValidationError({"binding_platform": "必做类型为「账号绑定」时必须选择绑定平台。"})
        if self.interaction_type == self.INTERACTION_JOIN_COMMUNITY:
            link = (self.interaction_config or {}).get("invite_link") or (self.interaction_config or {}).get(
                "telegram_invite_link"
            )
            if not link or not str(link).strip():
                raise ValidationError(
                    {
                        "interaction_config": "「加入社群」类任务请在 JSON 里填写 invite_link（或 telegram_invite_link），即用户要打开的 Telegram 链接。"
                    }
                )

    def save(self, *args, **kwargs):
        if self.interaction_type == self.INTERACTION_JOIN_COMMUNITY:
            self.binding_platform = self.BINDING_PLATFORM_NONE
        elif self.interaction_type != self.INTERACTION_ACCOUNT_BINDING:
            self.binding_platform = self.BINDING_PLATFORM_NONE
        if self.interaction_type == self.INTERACTION_NONE:
            self.verification_mode = None
            self.interaction_config = {}
        elif not self.verification_mode:
            self.verification_mode = self._default_verification_mode()
        super().save(*args, **kwargs)

    def _default_verification_mode(self):
        if self.interaction_type == self.INTERACTION_ACCOUNT_BINDING:
            if self.binding_platform == self.BINDING_TWITTER:
                return self.VERIFY_USER_SELF
            if self.binding_platform == self.BINDING_TELEGRAM:
                return self.VERIFY_USER_SELF
            if self.binding_platform == self.BINDING_TIKTOK:
                return self.VERIFY_USER_SELF
            if self.binding_platform in {
                self.BINDING_YOUTUBE,
                self.BINDING_INSTAGRAM,
                self.BINDING_FACEBOOK,
            }:
                return self.VERIFY_PROFILE_LINK
            return self.VERIFY_USER_SELF
        if self.interaction_type in (self.INTERACTION_FOLLOW, self.INTERACTION_COMMENT, self.INTERACTION_JOIN_COMMUNITY):
            return self.VERIFY_USER_SELF
        if self.interaction_type in (self.INTERACTION_WATCH_VIDEO, self.INTERACTION_EXTERNAL_VOTE):
            return self.VERIFY_SCREENSHOT
        return self.VERIFY_USER_SELF


class TaskApplication(models.Model):
    STATUS_PENDING = "pending"
    STATUS_ACCEPTED = "accepted"
    STATUS_REJECTED = "rejected"
    STATUS_CANCELLED = "cancelled"
    STATUS_CHOICES = (
        (STATUS_PENDING, "待处理"),
        (STATUS_ACCEPTED, "已录用"),
        (STATUS_REJECTED, "已拒绝"),
        (STATUS_CANCELLED, "已取消"),
    )

    task = models.ForeignKey(
        Task,
        on_delete=models.CASCADE,
        related_name="applications",
        verbose_name="报名任务",
        db_comment="被报名的任务ID",
    )
    applicant = models.ForeignKey(
        FrontendUser,
        on_delete=models.CASCADE,
        related_name="task_applications",
        verbose_name="报名用户",
        db_comment="报名用户ID",
    )
    proposal = models.TextField(blank=True, null=True, verbose_name="报名说明", db_comment="报名留言或补充说明")
    bound_username = models.CharField(
        max_length=128,
        blank=True,
        null=True,
        verbose_name="绑定账号用户名",
        db_comment="如推特 @handle，用于账号绑定类任务",
    )
    proof_image = models.ImageField(
        upload_to="task_applications/proof/%Y/%m/",
        blank=True,
        null=True,
        verbose_name="完成凭证截图",
        db_comment="看视频、外站投票等需截图审核时使用",
    )
    self_verified_at = models.DateTimeField(
        blank=True,
        null=True,
        verbose_name="用户标记完成时间",
        db_comment="用户点击验证完成的时间",
    )
    quoted_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        blank=True,
        null=True,
        validators=[MinValueValidator(Decimal("0.00"))],
        verbose_name="报价",
        db_comment="报名时的报价",
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
        verbose_name="报名状态",
        db_comment="报名处理状态",
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="报名时间", db_comment="报名创建时间")
    decided_at = models.DateTimeField(blank=True, null=True, verbose_name="处理时间", db_comment="发布人处理报名的时间")
    reward_paid_at = models.DateTimeField(
        blank=True,
        null=True,
        verbose_name="任务奖励已发放时间",
        db_comment="按任务 reward_usdt/reward_th_coin 入账后写入，防重复发奖",
    )
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间", db_comment="更新时间")

    class Meta:
        db_table = "task_application"
        verbose_name = "任务报名"
        verbose_name_plural = verbose_name
        unique_together = ("task", "applicant")
        ordering = ("-created_at",)

    def __str__(self):
        return f"{self.applicant.username} -> {self.task.title}"


class TaskCompletionRecord(TaskApplication):
    """
    与 task_application 同表；后台「任务完成记录」仅展示 status=已录用 的报名，
    便于运营查看完成/发奖情况，勿单独建物理表。
    """

    class Meta:
        proxy = True
        verbose_name = "任务完成记录"
        verbose_name_plural = verbose_name


class CheckInConfig(models.Model):
    """全局签到规则（后台仅维护一条记录）。"""

    daily_reward_usdt = models.DecimalField(
        max_digits=12,
        decimal_places=4,
        default=Decimal("0"),
        verbose_name="每日签到奖励 USDT",
        db_comment="成功签到一次增加的 USDT（可为 0）",
    )
    daily_reward_th_coin = models.DecimalField(
        max_digits=20,
        decimal_places=2,
        default=Decimal("0"),
        verbose_name="每日签到奖励 TH Coin",
        db_comment="成功签到一次增加的 TH Coin（可为 0）",
    )
    makeup_cost_th_coin = models.DecimalField(
        max_digits=20,
        decimal_places=2,
        default=Decimal("0"),
        verbose_name="补签消耗 TH Coin",
        db_comment="每次补签从 TH Coin 扣除的数量；为 0 表示不消耗",
    )
    weekly_makeup_limit = models.PositiveIntegerField(
        default=3,
        verbose_name="每周补签次数上限",
        db_comment="自然周内最多允许补签次数",
    )
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        db_table = "task_check_in_config"
        verbose_name = "签到参数配置"
        verbose_name_plural = verbose_name

    def __str__(self):
        return "签到参数（全局）"

    @classmethod
    def get(cls):
        obj = cls.objects.first()
        if obj is None:
            obj = cls.objects.create()
        return obj


class CheckInRecord(models.Model):
    """首页「每日签到」：按自然日（项目时区）一条记录。"""

    user = models.ForeignKey(
        FrontendUser,
        on_delete=models.CASCADE,
        related_name="check_ins",
        verbose_name="用户",
        db_comment="签到用户",
        db_constraint=False,
    )
    on_date = models.DateField(verbose_name="签到日期", db_comment="按 Asia/Shanghai 等当前激活时区的日历日")
    is_make_up = models.BooleanField(default=False, verbose_name="是否补签", db_comment="补签为 True")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="记录时间", db_comment="写入时间")

    class Meta:
        db_table = "task_check_in"
        verbose_name = "每日签到"
        verbose_name_plural = verbose_name
        unique_together = (("user", "on_date"),)
        ordering = ("-on_date", "-id")

    def __str__(self):
        return f"{self.user_id} {self.on_date}"


class TelegramStartInvitePending(models.Model):
    """
    用户通过 https://t.me/<Bot>?start=<payload> 打开 Bot 并点「启动」后，
    Telegram 会把 payload 随 /start 推给 Webhook；在用户随后 POST Mini App 登录前暂存于此，
    以便 initData 无 start_param 时仍能绑定 referrer。
    """

    telegram_id = models.BigIntegerField(unique=True, db_index=True, verbose_name="Telegram 用户 ID")
    start_payload = models.CharField(max_length=64, verbose_name="start 参数", db_comment="与 deep link ?start= 一致，最长 64")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        db_table = "taskhub_telegram_start_invite_pending"
        verbose_name = "Telegram /start 待绑定邀请"
        verbose_name_plural = verbose_name

    def __str__(self):
        return f"tg:{self.telegram_id} {self.start_payload!r}"


class IntegrationSecretConfig(models.Model):
    """
    全局第三方 API 密钥（后台仅维护一条）。
    字段有值时优先生效；留空则仍使用环境变量或 core/*_secrets.py（见 core/settings.py）。
    """

    telegram_bot_token = models.TextField(
        blank=True,
        default="",
        verbose_name="Telegram Bot Token",
        db_comment="Mini App 登录与入群校验 getChatMember；与 BotFather 一致",
    )
    twitter_bearer_token = models.TextField(
        blank=True,
        default="",
        verbose_name="Twitter / X Bearer Token",
        db_comment="API v2 只读 Bearer，用于转发/关注校验",
    )
    apify_api_token = models.TextField(
        blank=True,
        default="",
        verbose_name="Apify API Token",
        db_comment="Instagram / TikTok 等 Actor 调用",
    )
    apify_instagram_actor_id = models.CharField(
        max_length=256,
        blank=True,
        default="",
        verbose_name="Apify Instagram Actor ID",
        db_comment="默认 apify/instagram-profile-scraper；留空用 settings",
    )
    apify_instagram_timeout_sec = models.PositiveIntegerField(
        blank=True,
        null=True,
        verbose_name="Instagram 请求超时（秒）",
        db_comment="留空则使用 settings / 环境变量",
    )
    apify_tiktok_actor_id = models.CharField(
        max_length=256,
        blank=True,
        default="",
        verbose_name="Apify TikTok Actor ID",
        db_comment="默认 clockworks/tiktok-scraper",
    )
    apify_tiktok_timeout_sec = models.PositiveIntegerField(
        blank=True,
        null=True,
        verbose_name="TikTok 请求超时（秒）",
        db_comment="留空则使用 settings / 环境变量",
    )
    apify_tiktok_results_per_page = models.PositiveIntegerField(
        blank=True,
        null=True,
        verbose_name="TikTok Reposts 每页条数",
        db_comment="留空则使用 settings / 环境变量",
    )
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        db_table = "task_integration_secret_config"
        verbose_name = "第三方集成密钥"
        verbose_name_plural = verbose_name

    def __str__(self):
        return "第三方集成密钥（全局）"

    @classmethod
    def get(cls):
        obj = cls.objects.first()
        if obj is None:
            obj = cls.objects.create()
        return obj


class ApiToken(models.Model):
    user = models.OneToOneField(
        FrontendUser,
        on_delete=models.CASCADE,
        related_name="api_token",
        verbose_name="所属用户",
        db_comment="Token 对应的用户",
    )
    key = models.CharField(max_length=64, unique=True, verbose_name="Token", db_comment="鉴权令牌")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="签发时间", db_comment="Token 创建时间")
    last_used_at = models.DateTimeField(blank=True, null=True, verbose_name="最近使用时间", db_comment="最近一次鉴权请求时间")

    class Meta:
        db_table = "task_api_token"
        verbose_name = "API Token"
        verbose_name_plural = verbose_name

    def __str__(self):
        return f"{self.user.username} token"

    @classmethod
    def issue_for_user(cls, user):
        token_value = secrets.token_hex(32)
        token, _ = cls.objects.update_or_create(user=user, defaults={"key": token_value})
        token.last_used_at = timezone.now()
        token.save(update_fields=["last_used_at"])
        return token
