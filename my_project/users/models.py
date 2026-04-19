from django.db import models
from django.contrib.auth.hashers import make_password, check_password
import uuid

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

    class Meta:
        verbose_name = "会员"
        verbose_name_plural = "会员列表"
        db_table = "frontend_user" # 强制指定数据库表名，看起来更规范