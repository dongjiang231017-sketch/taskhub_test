from datetime import timedelta

from django.apps import apps
from django.db import models, transaction
from django.utils import timezone
from decimal import Decimal
from users.models import FrontendUser
from wallets.models import Wallet


class StakingProduct(models.Model):
    name = models.CharField(max_length=100, verbose_name="质押产品名称", db_comment="质押方案名称")
    annual_rate = models.DecimalField(max_digits=5, decimal_places=2, verbose_name="年化收益率", db_comment="质押产品的年化收益率，百分比")
    min_amount = models.DecimalField(max_digits=20, decimal_places=2, default=Decimal('0.00'), verbose_name="最低质押金额", db_comment="该产品允许的最低质押金额")
    max_amount = models.DecimalField(max_digits=20, decimal_places=2, blank=True, null=True, verbose_name="最高质押金额", db_comment="该产品允许的最高质押金额，可为空表示不限制")
    duration_days = models.IntegerField(blank=True, null=True, verbose_name="质押期限(天)", db_comment="建议质押期限，留空表示不限期")
    description = models.TextField(blank=True, null=True, verbose_name="产品说明", db_comment="质押产品的补充说明")
    image = models.ImageField(upload_to='staking_products/', blank=True, null=True, verbose_name="产品图片", db_comment="质押产品的展示图片")
    is_active = models.BooleanField(default=True, verbose_name="是否启用", db_comment="是否在前台或后台可用")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间", db_comment="质押产品创建时间")

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = "质押产品"
        verbose_name_plural = verbose_name
        ordering = ('-created_at',)


class StakeRecord(models.Model):
    STATUS_CHOICES = (
        ('active', '进行中'),
        ('completed', '已完成'),
        ('cancelled', '已取消'),
    )

    user = models.ForeignKey(FrontendUser, on_delete=models.CASCADE, related_name='stakes', verbose_name="质押用户", db_comment="发起质押的用户")
    product = models.ForeignKey(StakingProduct, on_delete=models.PROTECT, related_name='stakes', verbose_name="质押产品", db_comment="选择的质押产品")
    amount = models.DecimalField(max_digits=20, decimal_places=2, verbose_name="质押金额", db_comment="用户质押的余额金额")
    annual_rate = models.DecimalField(max_digits=5, decimal_places=2, verbose_name="年化收益率", db_comment="本次质押使用的年化收益率")
    start_at = models.DateTimeField(default=timezone.now, verbose_name="开始时间", db_comment="质押启动时间")
    last_settled_at = models.DateTimeField(blank=True, null=True, verbose_name="最后结算时间", db_comment="最近一次质押收益结算时间")
    total_earned = models.DecimalField(max_digits=20, decimal_places=2, default=Decimal('0.00'), verbose_name="累计收益", db_comment="质押已结算的总收益")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active', verbose_name="质押状态", db_comment="当前质押状态")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间", db_comment="质押记录创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间", db_comment="质押记录更新时间")

    class Meta:
        verbose_name = "质押记录"
        verbose_name_plural = verbose_name
        ordering = ('-created_at',)

    def save(self, *args, **kwargs):
        is_new = self.pk is None
        if self.annual_rate is None:
            self.annual_rate = self.product.annual_rate
        if self.start_at is None:
            self.start_at = timezone.now()

        if is_new:
            wallet = self.user.wallet
            if self.amount > wallet.balance:
                raise ValueError("余额不足，无法发起质押")

            old_balance = wallet.balance
            wallet.balance -= self.amount
            wallet.save(create_transaction=False)

            Transaction = apps.get_model('wallets', 'Transaction')
            Transaction.objects.create(
                wallet=wallet,
                asset=Transaction.ASSET_USDT,
                amount=-self.amount,
                before_balance=old_balance,
                after_balance=wallet.balance,
                change_type='cost',
                remark=f'质押扣款：{self.product.name}',
            )

        super().save(*args, **kwargs)

    def settle_daily(self):
        if self.status != 'active':
            return None

        now = timezone.now()
        if self.last_settled_at is None:
            next_settlement = self.start_at + timedelta(days=1)
        else:
            next_settlement = self.last_settled_at + timedelta(days=1)

        if now < next_settlement:
            return None

        income = (self.amount * self.annual_rate / Decimal('100.00')) / Decimal('365.00')
        income = income.quantize(Decimal('0.01'))
        if income == Decimal('0.00'):
            self.last_settled_at = now
            self.save(update_fields=['last_settled_at'])
            return None

        wallet = self.user.wallet
        old_balance = wallet.balance
        wallet.balance += income
        wallet.save(create_transaction=False)

        Transaction = apps.get_model('wallets', 'Transaction')
        Transaction.objects.create(
            wallet=wallet,
            asset=Transaction.ASSET_USDT,
            amount=income,
            before_balance=old_balance,
            after_balance=wallet.balance,
            change_type='reward',
            remark=f'质押收益：{self.product.name}',
        )

        self.total_earned += income
        self.last_settled_at = now
        self.save(update_fields=['total_earned', 'last_settled_at'])
        return income

    def __str__(self):
        return f"{self.user.username} - {self.product.name} - {self.amount}"
