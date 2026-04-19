from django.apps import apps
from django.db import models, transaction
from decimal import Decimal
from users.models import FrontendUser # 引入前台用户模型

class Wallet(models.Model):
    # 这里不再关联 admin 的 user，而是关联我们独立的前台用户
    user = models.OneToOneField(FrontendUser, on_delete=models.CASCADE, related_name='wallet', verbose_name="所属用户", db_comment="关联的前台用户ID")
    balance = models.DecimalField(max_digits=20, decimal_places=2, default=Decimal('0.00'), verbose_name="USDT", db_comment="用户当前可提现或消费的 USDT 余额")
    frozen = models.DecimalField(max_digits=20, decimal_places=2, default=Decimal('0.00'), verbose_name="TH Coin", db_comment="TH Coin 数量（含冻结/锁定场景）")

    class Meta:
        verbose_name = "用户钱包"
        verbose_name_plural = verbose_name
        db_table = "frontend_wallet"

    def save(self, *args, create_transaction=True, **kwargs):
        old_balance = None
        old_frozen = None
        is_update = self.pk is not None
        if is_update:
            try:
                old = Wallet.objects.get(pk=self.pk)
                old_balance = old.balance
                old_frozen = old.frozen
            except Wallet.DoesNotExist:
                old = None
        else:
            old = None

        # create_transaction=False 时由调用方（如签到 API）已包在外层 atomic 内；
        # 此处不再套一层 atomic，避免与 MySQL GTID 下非事务表（如 MyISAM 的 django_session）混用触发 1785。
        if not create_transaction:
            super().save(*args, **kwargs)
            return

        with transaction.atomic():
            super().save(*args, **kwargs)
            Transaction = apps.get_model('wallets', 'Transaction')
            if old is None:
                if self.balance != Decimal('0.00'):
                    Transaction.objects.create(
                        wallet=self,
                        amount=self.balance,
                        before_balance=Decimal('0.00'),
                        after_balance=self.balance,
                        change_type='recharge',
                        remark='初始化 USDT',
                    )
                if self.frozen != Decimal('0.00'):
                    Transaction.objects.create(
                        wallet=self,
                        amount=self.frozen,
                        before_balance=Decimal('0.00'),
                        after_balance=self.frozen,
                        change_type='adjust',
                        remark='初始化 TH Coin',
                    )
            else:
                if self.balance != old_balance:
                    Transaction.objects.create(
                        wallet=self,
                        amount=self.balance - old_balance,
                        before_balance=old_balance,
                        after_balance=self.balance,
                        change_type='admin_adjust',
                        remark='管理员后台拨币：USDT',
                    )
                if self.frozen != old_frozen:
                    Transaction.objects.create(
                        wallet=self,
                        amount=self.frozen - old_frozen,
                        before_balance=old_frozen,
                        after_balance=self.frozen,
                        change_type='admin_adjust',
                        remark='管理员后台拨币：TH Coin',
                    )

class Transaction(models.Model):
    TX_TYPE = (
        ('recharge', '充值'),
        ('withdraw', '提现'),
        ('reward', '推荐奖励'),
        ('task_reward', '任务奖励'),
        ('cost', '消费'),
        ('adjust', '调账'),
        ('admin_adjust', '后台拨币'),
        ('check_in', '每日签到'),
        ('check_in_makeup', '补签奖励'),
        ('check_in_makeup_cost', '补签消耗'),
    )
    wallet = models.ForeignKey(Wallet, on_delete=models.CASCADE, related_name='logs', verbose_name="所属钱包", db_comment="发生账变的钱包ID")
    amount = models.DecimalField(max_digits=20, decimal_places=2, verbose_name="变动金额", db_comment="本次账变金额，正数增加，负数减少")
    before_balance = models.DecimalField(max_digits=20, decimal_places=2, verbose_name="变动前", db_comment="变动前的钱包余额")
    after_balance = models.DecimalField(max_digits=20, decimal_places=2, verbose_name="变动后", db_comment="变动后的钱包余额")
    change_type = models.CharField(max_length=20, choices=TX_TYPE, verbose_name="账变类型", db_comment="业务类型：充值、提现等")
    remark = models.CharField(max_length=255, blank=True, null=True, verbose_name="备注", db_comment="账变具体说明")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="时间", db_comment="账变发生的时间")

    class Meta:
        verbose_name = "账变记录"
        verbose_name_plural = verbose_name
        db_table = "frontend_transaction"


class WithdrawalRequest(models.Model):
    """用户链上提现申请（与 USDT 余额扣款对应；后台可改状态或线下打款）。"""

    STATUS_PROCESSING = "processing"
    STATUS_COMPLETED = "completed"
    STATUS_REJECTED = "rejected"
    STATUS_CHOICES = (
        (STATUS_PROCESSING, "处理中"),
        (STATUS_COMPLETED, "已完成"),
        (STATUS_REJECTED, "已拒绝"),
    )

    user = models.ForeignKey(
        FrontendUser,
        on_delete=models.CASCADE,
        related_name="withdrawal_requests",
        verbose_name="用户",
        db_comment="申请人",
    )
    amount = models.DecimalField(
        max_digits=20,
        decimal_places=2,
        verbose_name="提现金额(扣款)",
        db_comment="从钱包扣除的 USDT 总额（含手续费时即用户输入的总扣款）",
    )
    fee = models.DecimalField(
        max_digits=20,
        decimal_places=2,
        default=Decimal("0.00"),
        verbose_name="手续费",
        db_comment="从 amount 中拆分的手续费；预计到账 = amount - fee",
    )
    chain = models.CharField(max_length=32, default="BEP20", verbose_name="链", db_comment="如 BEP20")
    to_address = models.CharField(max_length=128, verbose_name="收款地址", db_comment="用户填写的链上地址")
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_PROCESSING,
        verbose_name="状态",
        db_comment="处理中/已完成/已拒绝",
    )
    reject_reason = models.CharField(
        max_length=255,
        blank=True,
        default="",
        verbose_name="拒绝原因",
        db_comment="拒绝时填写",
    )
    debit_transaction = models.ForeignKey(
        Transaction,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="withdrawal_requests",
        verbose_name="扣款账变",
        db_comment="对应钱包 USDT 扣款流水",
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        verbose_name = "提现申请"
        verbose_name_plural = verbose_name
        db_table = "frontend_withdrawal_request"
        ordering = ("-created_at",)

    @property
    def net_amount(self) -> Decimal:
        return (self.amount - self.fee).quantize(Decimal("0.01"))