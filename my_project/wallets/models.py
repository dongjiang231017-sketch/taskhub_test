from decimal import Decimal

from django.apps import apps
from django.core.validators import MinValueValidator
from django.db import models, transaction
from django.utils import timezone

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
                        asset=Transaction.ASSET_USDT,
                        amount=self.balance,
                        before_balance=Decimal('0.00'),
                        after_balance=self.balance,
                        change_type='recharge',
                        remark='初始化 USDT',
                    )
                if self.frozen != Decimal('0.00'):
                    Transaction.objects.create(
                        wallet=self,
                        asset=Transaction.ASSET_TH_COIN,
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
                        asset=Transaction.ASSET_USDT,
                        amount=self.balance - old_balance,
                        before_balance=old_balance,
                        after_balance=self.balance,
                        change_type='admin_adjust',
                        remark='管理员后台拨币：USDT',
                    )
                if self.frozen != old_frozen:
                    Transaction.objects.create(
                        wallet=self,
                        asset=Transaction.ASSET_TH_COIN,
                        amount=self.frozen - old_frozen,
                        before_balance=old_frozen,
                        after_balance=self.frozen,
                        change_type='admin_adjust',
                        remark='管理员后台拨币：TH Coin',
                    )

class Transaction(models.Model):
    ASSET_USDT = "usdt"
    ASSET_TH_COIN = "th_coin"
    ASSET_CHOICES = (
        (ASSET_USDT, "USDT"),
        (ASSET_TH_COIN, "TH Coin"),
    )
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
        ('invite_achievement', '邀请成就奖励'),
        ('daily_task', '每日任务奖励'),
    )
    wallet = models.ForeignKey(Wallet, on_delete=models.CASCADE, related_name='logs', verbose_name="所属钱包", db_comment="发生账变的钱包ID")
    asset = models.CharField(
        max_length=16,
        choices=ASSET_CHOICES,
        default=ASSET_USDT,
        db_index=True,
        verbose_name="资产",
        db_comment="账变归属资产：USDT 或 TH Coin，用于前台分开展示明细",
    )
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

    def save(self, *args, **kwargs):
        remark = (self.remark or "").lower()
        if "th coin" in remark or "冻结" in remark:
            self.asset = self.ASSET_TH_COIN
        elif not self.asset:
            self.asset = self.ASSET_USDT
        super().save(*args, **kwargs)


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


class RechargeNetworkConfig(models.Model):
    """USDT 自动充值网络配置。"""

    CHAIN_TRC20 = "TRC20"
    CHAIN_ERC20 = "ERC20"
    CHAIN_BEP20 = "BEP20"
    CHAIN_CHOICES = (
        (CHAIN_TRC20, "TRC20"),
        (CHAIN_ERC20, "ERC20"),
        (CHAIN_BEP20, "BEP20"),
    )

    chain = models.CharField(max_length=16, choices=CHAIN_CHOICES, unique=True, verbose_name="充值网络")
    display_name = models.CharField(max_length=64, verbose_name="展示名称", db_comment="如 USDT-TRC20")
    deposit_address = models.CharField(
        max_length=160,
        blank=True,
        default="",
        verbose_name="旧版固定充值地址（已弃用）",
        db_comment="旧版人工提单模式遗留字段；新逻辑使用每个用户的独立充值地址",
    )
    token_contract_address = models.CharField(
        max_length=160,
        blank=True,
        default="",
        verbose_name="USDT 合约地址",
        db_comment="ERC20/BEP20/TRC20 对应的 USDT 合约地址",
    )
    rpc_endpoint = models.CharField(
        max_length=255,
        blank=True,
        default="",
        verbose_name="RPC / API 地址",
        db_comment="EVM 填 JSON-RPC；TRON 填 fullnode / TronGrid 根地址",
    )
    api_key = models.TextField(
        blank=True,
        default="",
        verbose_name="链上 API Key",
        db_comment="如 TronGrid API Key；留空则按公共节点访问",
    )
    master_mnemonic = models.TextField(
        blank=True,
        default="",
        verbose_name="HD 主助记词",
        db_comment="用于给每个用户派生独立充值地址；请妥善保管",
    )
    mnemonic_passphrase = models.CharField(
        max_length=255,
        blank=True,
        default="",
        verbose_name="助记词附加密码",
        db_comment="若助记词无附加密码可留空",
    )
    collector_address = models.CharField(
        max_length=160,
        blank=True,
        default="",
        verbose_name="归集地址",
        db_comment="链上充值自动归集到的总地址",
    )
    collector_private_key = models.TextField(
        blank=True,
        default="",
        verbose_name="归集/手续费私钥",
        db_comment="用于给充值地址补 Gas 及归集 USDT；建议仅管理员可见",
    )
    min_amount_usdt = models.DecimalField(
        max_digits=20,
        decimal_places=2,
        default=Decimal("1.00"),
        validators=[MinValueValidator(Decimal("0.01"))],
        verbose_name="最低充值 USDT",
    )
    confirmations_required = models.PositiveSmallIntegerField(default=1, verbose_name="确认数要求")
    token_decimals = models.PositiveSmallIntegerField(default=6, verbose_name="Token 精度")
    evm_chain_id = models.PositiveBigIntegerField(
        blank=True,
        null=True,
        verbose_name="EVM Chain ID",
        db_comment="ERC20/BEP20 使用；TRC20 留空",
    )
    next_derivation_index = models.PositiveIntegerField(default=0, verbose_name="下一个派生序号")
    scan_from_block = models.BigIntegerField(
        blank=True,
        null=True,
        verbose_name="扫链起始块",
        db_comment="EVM 网络首次扫链的起始块；留空则首次从最近区块回溯",
    )
    sweep_enabled = models.BooleanField(default=True, verbose_name="自动归集")
    min_sweep_amount_usdt = models.DecimalField(
        max_digits=20,
        decimal_places=2,
        default=Decimal("1.00"),
        validators=[MinValueValidator(Decimal("0.01"))],
        verbose_name="最小归集 USDT",
    )
    topup_native_amount = models.DecimalField(
        max_digits=20,
        decimal_places=8,
        default=Decimal("0.00030000"),
        validators=[MinValueValidator(Decimal("0"))],
        verbose_name="补 Gas 数量",
        db_comment="EVM 为 ETH/BNB，TRC20 为 TRX",
    )
    token_transfer_gas_limit = models.PositiveIntegerField(default=100000, verbose_name="Token 转账 Gas Limit")
    tron_fee_limit_sun = models.PositiveBigIntegerField(default=30000000, verbose_name="TRON Fee Limit (sun)")
    sort_order = models.PositiveSmallIntegerField(default=0, verbose_name="排序")
    is_active = models.BooleanField(default=True, verbose_name="启用")
    instructions = models.TextField(blank=True, default="", verbose_name="充值说明")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        verbose_name = "充值网络配置"
        verbose_name_plural = verbose_name
        db_table = "wallet_recharge_network_config"
        ordering = ("sort_order", "id")

    def __str__(self):
        return f"{self.display_name} ({self.chain})"

    @property
    def is_evm(self) -> bool:
        return self.chain in {self.CHAIN_ERC20, self.CHAIN_BEP20}

    @property
    def is_tron(self) -> bool:
        return self.chain == self.CHAIN_TRC20

    @property
    def native_symbol(self) -> str:
        if self.chain == self.CHAIN_ERC20:
            return "ETH"
        if self.chain == self.CHAIN_BEP20:
            return "BNB"
        return "TRX"

    @property
    def is_auto_ready(self) -> bool:
        if not self.is_active:
            return False
        required = [
            (self.token_contract_address or "").strip(),
            (self.rpc_endpoint or "").strip(),
            (self.master_mnemonic or "").strip(),
            (self.collector_address or "").strip(),
            (self.collector_private_key or "").strip(),
        ]
        return all(required)

    def build_account_path(self, index: int) -> str:
        coin_type = "195" if self.is_tron else "60"
        return f"m/44'/{coin_type}'/0'/0/{int(index)}"


class UserRechargeAddress(models.Model):
    STATUS_ACTIVE = "active"
    STATUS_ARCHIVED = "archived"
    STATUS_CHOICES = (
        (STATUS_ACTIVE, "启用"),
        (STATUS_ARCHIVED, "归档"),
    )

    user = models.ForeignKey(
        FrontendUser,
        on_delete=models.CASCADE,
        related_name="recharge_addresses",
        verbose_name="用户",
    )
    network = models.ForeignKey(
        RechargeNetworkConfig,
        on_delete=models.CASCADE,
        related_name="user_addresses",
        verbose_name="充值网络",
    )
    address = models.CharField(max_length=160, unique=True, verbose_name="充值地址")
    address_hex = models.CharField(
        max_length=128,
        blank=True,
        default="",
        verbose_name="地址 Hex",
        db_comment="TRON 用于链上接口的 41 前缀 hex；EVM 为 0x 地址",
    )
    derivation_index = models.PositiveIntegerField(verbose_name="派生序号")
    account_path = models.CharField(max_length=128, verbose_name="派生路径")
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_ACTIVE, verbose_name="状态")
    last_seen_at = models.DateTimeField(blank=True, null=True, verbose_name="最近发现入账时间")
    last_swept_at = models.DateTimeField(blank=True, null=True, verbose_name="最近归集时间")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        verbose_name = "用户充值地址"
        verbose_name_plural = verbose_name
        db_table = "wallet_user_recharge_address"
        ordering = ("network__sort_order", "user_id", "id")
        constraints = [
            models.UniqueConstraint(fields=("user", "network"), name="uniq_user_recharge_address"),
            models.UniqueConstraint(fields=("network", "derivation_index"), name="uniq_network_derivation_index"),
        ]

    def __str__(self):
        return f"{self.user} {self.network.chain} {self.address}"


class RechargeRequest(models.Model):
    """链上充值流水：自动发现、自动确认、自动入账。"""

    STATUS_PENDING = "pending"
    STATUS_COMPLETED = "completed"
    STATUS_REJECTED = "rejected"
    STATUS_CHOICES = (
        (STATUS_PENDING, "确认中"),
        (STATUS_COMPLETED, "已到账"),
        (STATUS_REJECTED, "失败"),
    )
    SOURCE_MANUAL = "manual_submission"
    SOURCE_AUTO = "chain_auto"
    SOURCE_CHOICES = (
        (SOURCE_MANUAL, "人工提单（旧版）"),
        (SOURCE_AUTO, "链上自动发现"),
    )
    SWEEP_NONE = "none"
    SWEEP_PENDING = "pending"
    SWEEP_COMPLETED = "completed"
    SWEEP_FAILED = "failed"
    SWEEP_CHOICES = (
        (SWEEP_NONE, "未归集"),
        (SWEEP_PENDING, "归集中"),
        (SWEEP_COMPLETED, "已归集"),
        (SWEEP_FAILED, "归集失败"),
    )

    user = models.ForeignKey(
        FrontendUser,
        on_delete=models.CASCADE,
        related_name="recharge_requests",
        verbose_name="用户",
        db_comment="该笔链上充值归属的前台用户",
    )
    network = models.ForeignKey(
        RechargeNetworkConfig,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="recharge_requests",
        verbose_name="网络配置",
    )
    user_address = models.ForeignKey(
        UserRechargeAddress,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="recharge_requests",
        verbose_name="用户充值地址",
    )
    amount = models.DecimalField(
        max_digits=20,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
        verbose_name="充值金额 USDT",
    )
    chain = models.CharField(max_length=16, choices=RechargeNetworkConfig.CHAIN_CHOICES, verbose_name="充值网络")
    deposit_address = models.CharField(
        max_length=160,
        blank=True,
        default="",
        verbose_name="收款地址快照",
        db_comment="用户专属充值地址快照",
    )
    from_address = models.CharField(max_length=160, blank=True, default="", verbose_name="付款地址")
    tx_hash = models.CharField(max_length=160, verbose_name="交易哈希 TxHash")
    log_index = models.PositiveIntegerField(default=0, verbose_name="日志序号")
    source_type = models.CharField(
        max_length=20,
        choices=SOURCE_CHOICES,
        default=SOURCE_MANUAL,
        verbose_name="来源",
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING, verbose_name="状态")
    reject_reason = models.CharField(max_length=255, blank=True, default="", verbose_name="拒绝原因")
    token_contract_address = models.CharField(max_length=160, blank=True, default="", verbose_name="合约地址")
    block_number = models.BigIntegerField(blank=True, null=True, verbose_name="区块高度")
    confirmations = models.PositiveIntegerField(default=0, verbose_name="确认数")
    credited_transaction = models.ForeignKey(
        Transaction,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="recharge_requests",
        verbose_name="入账账变",
    )
    credited_at = models.DateTimeField(blank=True, null=True, verbose_name="到账时间")
    reviewed_at = models.DateTimeField(blank=True, null=True, verbose_name="审核时间")
    sweep_status = models.CharField(
        max_length=20,
        choices=SWEEP_CHOICES,
        default=SWEEP_NONE,
        verbose_name="归集状态",
    )
    sweep_tx_hash = models.CharField(max_length=160, blank=True, default="", verbose_name="归集交易哈希")
    swept_at = models.DateTimeField(blank=True, null=True, verbose_name="归集完成时间")
    last_error = models.CharField(max_length=255, blank=True, default="", verbose_name="最近错误")
    raw_payload = models.JSONField(default=dict, blank=True, verbose_name="链上原始载荷")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="提交时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        verbose_name = "充值申请"
        verbose_name_plural = verbose_name
        db_table = "wallet_recharge_request"
        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(fields=("chain", "tx_hash", "log_index"), name="uniq_recharge_chain_tx_hash_log"),
        ]

    def __str__(self):
        return f"{self.user} {self.amount} USDT {self.chain}"

    def credit_to_wallet(self) -> Transaction:
        """链上确认完成后入账；幂等，避免重复发放。"""
        if self.credited_transaction_id:
            return self.credited_transaction
        with transaction.atomic():
            req = RechargeRequest.objects.select_for_update().select_related("user").get(pk=self.pk)
            if req.credited_transaction_id:
                self.refresh_from_db()
                return self.credited_transaction
            Wallet.objects.get_or_create(user=req.user)
            wallet = Wallet.objects.select_for_update().get(user=req.user)
            old_balance = wallet.balance
            new_balance = (old_balance + req.amount).quantize(Decimal("0.01"))
            tx = Transaction.objects.create(
                wallet=wallet,
                asset=Transaction.ASSET_USDT,
                amount=req.amount,
                before_balance=old_balance,
                after_balance=new_balance,
                change_type="recharge",
                remark=f"USDT 充值 {req.chain}：{req.tx_hash}"[:250],
            )
            wallet.balance = new_balance
            wallet.save(create_transaction=False)
            req.status = RechargeRequest.STATUS_COMPLETED
            req.credited_transaction = tx
            now = timezone.now()
            req.reviewed_at = now
            req.credited_at = now
            req.save(
                update_fields=[
                    "status",
                    "credited_transaction",
                    "reviewed_at",
                    "credited_at",
                    "updated_at",
                ]
            )
            self.refresh_from_db()
            return tx

    def mark_sweep_pending(self, tx_hash: str) -> None:
        self.sweep_status = self.SWEEP_PENDING
        self.sweep_tx_hash = (tx_hash or "").strip()
        self.last_error = ""
        self.save(update_fields=["sweep_status", "sweep_tx_hash", "last_error", "updated_at"])

    def mark_swept(self) -> None:
        now = timezone.now()
        self.sweep_status = self.SWEEP_COMPLETED
        self.swept_at = now
        self.last_error = ""
        self.save(update_fields=["sweep_status", "swept_at", "last_error", "updated_at"])

    def mark_sweep_failed(self, error: str) -> None:
        self.sweep_status = self.SWEEP_FAILED
        self.last_error = (error or "")[:255]
        self.save(update_fields=["sweep_status", "last_error", "updated_at"])
