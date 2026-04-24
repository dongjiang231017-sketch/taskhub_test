from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import models
from django.contrib.auth.hashers import make_password, check_password
import uuid

from taskhub.locale_prefs import DEFAULT_PREFERRED_LANGUAGE, SUPPORTED_LANGUAGE_CHOICES

class FrontendUser(models.Model):
    """
    独立的前台用户表（与后台管理员完全隔离）
    """
    phone = models.CharField(
        max_length=11,
        unique=True,
        blank=True,
        null=True,
        verbose_name="手机号",
        db_comment="可选；Telegram 登录用户可为空，手机号注册登录时必填",
    )
    telegram_id = models.BigIntegerField(
        blank=True,
        null=True,
        unique=True,
        verbose_name="Telegram 用户 ID",
        db_comment="Mini App / Telegram 登录时的 tg user id",
    )
    telegram_username = models.CharField(
        max_length=64,
        blank=True,
        null=True,
        verbose_name="Telegram 用户名",
        db_comment="不含 @ 的 username，可能为空",
    )
    preferred_language = models.CharField(
        max_length=16,
        choices=SUPPORTED_LANGUAGE_CHOICES,
        default=DEFAULT_PREFERRED_LANGUAGE,
        verbose_name="界面语言",
        db_comment="机器人入口 / Mini App 首选语言",
    )
    password = models.CharField(max_length=128, verbose_name="登录密码", db_comment="加密存储的登录密码")
    
    # 新增字段
    username = models.CharField(max_length=50, unique=True, verbose_name="用户名", db_comment="用户昵称或显示名称")
    pay_password = models.CharField(max_length=128, blank=True, null=True, verbose_name="支付密码", db_comment="加密存储的支付密码，用于支付验证")
    membership_level = models.IntegerField(default=1, verbose_name="会员等级", db_comment="用户会员等级，1=普通会员，2=VIP，3=超级VIP等")
    
    invite_code = models.CharField(max_length=10, unique=True, verbose_name="我的邀请码", db_comment="系统生成的唯一邀请码")
    
    referrer = models.ForeignKey(
        'self', 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name='children',
        verbose_name="推荐人",
        db_comment="上级推荐人的ID"
    )
    
    status = models.BooleanField(default=True, verbose_name="账号状态", db_comment="True为正常, False为拉黑封禁")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="注册时间", db_comment="用户注册的时间")

    def save(self, *args, **kwargs):
        # 1. 自动生成邀请码
        if not self.invite_code:
            self.invite_code = uuid.uuid4().hex[:8].upper()
        # 2. 拦截密码，如果是明文则自动加密处理
        if self.password and not self.password.startswith('pbkdf2_'):
            self.password = make_password(self.password)
        # 3. 拦截支付密码，如果是明文则自动加密处理
        if self.pay_password and not self.pay_password.startswith('pbkdf2_'):
            self.pay_password = make_password(self.pay_password)
        super().save(*args, **kwargs)

    # 验证密码的方法（留给前台登录接口用）
    def verify_password(self, raw_password):
        return check_password(raw_password, self.password)
    
    # 验证支付密码的方法
    def verify_pay_password(self, raw_pay_password):
        if not self.pay_password:
            return False
        return check_password(raw_pay_password, self.pay_password)

    def __str__(self):
        return f"{self.username} (#{self.id})"

    class Meta:
        verbose_name = "会员"
        verbose_name_plural = "会员列表"
        db_table = "frontend_user" # 强制指定数据库表名，看起来更规范


class AgentProfile(models.Model):
    """代理后台账号：为某个前台会员开通代理权限，并自动维护内部桥接 staff 账号。"""

    backend_user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        db_constraint=False,
        related_name="agent_profile",
        verbose_name="系统桥接账号",
        db_comment="系统自动维护的 Django staff 账号，用于承载 /agent-admin/ 后台会话。",
    )
    root_user = models.OneToOneField(
        FrontendUser,
        on_delete=models.CASCADE,
        db_constraint=False,
        related_name="agent_profile",
        verbose_name="代理前台会员",
        db_comment="该前台用户既是代理后台登录身份，也是伞下数据根节点。",
    )
    include_self = models.BooleanField(
        default=True,
        verbose_name="包含代理本人",
        db_comment="开启后代理后台可见根节点本人及所有下级；关闭后仅可见下级。",
    )
    is_active = models.BooleanField(default=True, verbose_name="是否启用")
    remark = models.CharField(max_length=255, blank=True, default="", verbose_name="备注")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        db_table = "frontend_agent_profile"
        verbose_name = "代理后台账号"
        verbose_name_plural = verbose_name

    def __str__(self):
        return f"{self.root_user} -> 代理后台"

    @staticmethod
    def backend_username_for_root_user(root_user_id: int) -> str:
        return f"agent_member_{root_user_id}"

    @property
    def login_identity(self) -> str:
        if not self.root_user_id:
            return "—"
        phone = (self.root_user.phone or "").strip()
        if phone:
            return f"{self.root_user.username} / {phone}"
        return self.root_user.username

    def ensure_backend_user(self):
        if not self.root_user_id:
            return None

        User = get_user_model()
        desired_username = self.backend_username_for_root_user(self.root_user_id)
        user = self.backend_user
        if user is None:
            user, _ = User.objects.get_or_create(username=desired_username)
        elif user.username != desired_username:
            replacement = User.objects.filter(username=desired_username).exclude(pk=user.pk).first()
            user = replacement or user
            user.username = desired_username

        user.first_name = (self.root_user.username or "")[:150]
        user.last_name = "Agent"
        user.email = ""
        user.is_staff = True
        user.is_superuser = False
        user.is_active = self.is_active
        user.set_unusable_password()
        user.save()
        return user

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        backend_user = self.ensure_backend_user()
        if backend_user is not None and self.backend_user_id != backend_user.pk:
            type(self).objects.filter(pk=self.pk).update(backend_user=backend_user)
            self.backend_user = backend_user
