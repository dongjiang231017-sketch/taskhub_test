from django.contrib import admin

from .models import RechargeNetworkConfig, RechargeRequest, Transaction, UserRechargeAddress, WithdrawalRequest


@admin.register(RechargeNetworkConfig)
class RechargeNetworkConfigAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "sort_order",
        "chain",
        "display_name",
        "collector_address_short",
        "token_contract_address_short",
        "min_amount_usdt",
        "confirmations_required",
        "is_auto_ready_flag",
        "is_active",
        "updated_at",
    )
    list_filter = ("is_active", "chain")
    search_fields = ("chain", "display_name", "collector_address", "token_contract_address")
    ordering = ("sort_order", "id")
    fieldsets = (
        ("网络", {"fields": ("sort_order", "chain", "display_name", "is_active")}),
        (
            "链上参数",
            {
                "fields": (
                    "token_contract_address",
                    "rpc_endpoint",
                    "api_key",
                    "evm_chain_id",
                    "token_decimals",
                    "min_amount_usdt",
                    "confirmations_required",
                    "scan_from_block",
                )
            },
        ),
        (
            "地址派生与归集",
            {
                "fields": (
                    "master_mnemonic",
                    "mnemonic_passphrase",
                    "collector_address",
                    "collector_private_key",
                    "next_derivation_index",
                    "sweep_enabled",
                    "min_sweep_amount_usdt",
                    "topup_native_amount",
                    "token_transfer_gas_limit",
                    "tron_fee_limit_sun",
                )
            },
        ),
        ("说明", {"fields": ("instructions",)}),
        ("系统", {"fields": ("updated_at",)}),
    )
    readonly_fields = ("updated_at", "next_derivation_index")

    @admin.display(description="归集地址")
    def collector_address_short(self, obj):
        s = obj.collector_address or ""
        if not s:
            return "未配置"
        if len(s) <= 24:
            return s
        return f"{s[:12]}…{s[-10:]}"

    @admin.display(description="USDT 合约")
    def token_contract_address_short(self, obj):
        s = obj.token_contract_address or ""
        if not s:
            return "未配置"
        if len(s) <= 24:
            return s
        return f"{s[:12]}…{s[-10:]}"

    @admin.display(description="自动充值就绪", boolean=True)
    def is_auto_ready_flag(self, obj):
        return obj.is_auto_ready


@admin.register(UserRechargeAddress)
class UserRechargeAddressAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "user",
        "network",
        "address_short",
        "derivation_index",
        "status",
        "last_seen_at",
        "last_swept_at",
        "created_at",
    )
    list_filter = ("network__chain", "status", "created_at")
    search_fields = ("user__username", "user__phone", "address")
    readonly_fields = (
        "user",
        "network",
        "address",
        "address_hex",
        "derivation_index",
        "account_path",
        "last_seen_at",
        "last_swept_at",
        "created_at",
        "updated_at",
    )
    list_select_related = ("user", "network")
    ordering = ("-created_at",)

    def has_add_permission(self, request):
        return False

    @admin.display(description="充值地址")
    def address_short(self, obj):
        s = obj.address or ""
        if len(s) <= 24:
            return s
        return f"{s[:12]}…{s[-10:]}"


@admin.register(RechargeRequest)
class RechargeRequestAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "user",
        "network",
        "amount",
        "chain",
        "tx_hash_short",
        "status",
        "confirmations",
        "sweep_status",
        "created_at",
        "credited_at",
    )
    list_display_links = ("id", "user")
    list_filter = ("status", "sweep_status", "source_type", "chain", "created_at")
    search_fields = ("user__username", "user__phone", "user__invite_code", "tx_hash", "from_address", "deposit_address")
    readonly_fields = (
        "user",
        "network",
        "user_address",
        "amount",
        "chain",
        "deposit_address",
        "from_address",
        "tx_hash",
        "log_index",
        "source_type",
        "token_contract_address",
        "block_number",
        "confirmations",
        "credited_transaction",
        "credited_at",
        "sweep_tx_hash",
        "swept_at",
        "raw_payload",
        "created_at",
        "updated_at",
        "reviewed_at",
    )
    date_hierarchy = "created_at"
    ordering = ("-created_at",)
    list_per_page = 50
    list_select_related = ("user", "network", "user_address", "credited_transaction")

    fieldsets = (
        (
            "充值信息",
            {
                "fields": (
                    "user",
                    "network",
                    "user_address",
                    "amount",
                    "chain",
                    "deposit_address",
                    "from_address",
                    "tx_hash",
                    "log_index",
                    "source_type",
                )
            },
        ),
        (
            "链上状态",
            {
                "fields": (
                    "status",
                    "reject_reason",
                    "token_contract_address",
                    "block_number",
                    "confirmations",
                    "credited_transaction",
                    "credited_at",
                    "reviewed_at",
                )
            },
        ),
        ("归集", {"fields": ("sweep_status", "sweep_tx_hash", "swept_at", "last_error")}),
        ("原始数据", {"fields": ("raw_payload",), "classes": ("collapse",)}),
        ("时间", {"fields": ("created_at", "updated_at")}),
    )

    def has_add_permission(self, request):
        return False

    @admin.display(description="TxHash")
    def tx_hash_short(self, obj):
        s = obj.tx_hash or ""
        if len(s) <= 24:
            return s
        return f"{s[:12]}…{s[-10:]}"


@admin.register(WithdrawalRequest)
class WithdrawalRequestAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "user",
        "amount",
        "fee",
        "net_amount_display",
        "chain",
        "to_address_short",
        "status",
        "created_at",
        "updated_at",
    )
    list_display_links = ("id", "user")
    list_filter = ("status", "chain", "created_at")
    search_fields = ("user__username", "user__phone", "user__invite_code", "to_address", "id")
    readonly_fields = (
        "user",
        "amount",
        "fee",
        "chain",
        "to_address",
        "created_at",
        "updated_at",
        "debit_transaction",
    )
    date_hierarchy = "created_at"
    ordering = ("-created_at",)
    list_per_page = 50
    list_select_related = ("user", "debit_transaction")

    fieldsets = (
        (None, {"fields": ("user", "amount", "fee", "chain", "to_address", "status", "reject_reason")}),
        ("关联", {"fields": ("debit_transaction",), "classes": ("collapse",)}),
        ("时间", {"fields": ("created_at", "updated_at")}),
    )

    @admin.display(description="预计到账(USDT)")
    def net_amount_display(self, obj):
        return str(obj.net_amount)

    @admin.display(description="收款地址")
    def to_address_short(self, obj):
        s = obj.to_address or ""
        if len(s) <= 20:
            return s
        return f"{s[:10]}…{s[-8:]}"


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = ('id', 'wallet_user', 'wallet_id', 'wallet_type', 'amount', 'before_balance', 'after_balance', 'change_type', 'created_at')
    list_display_links = ('id', 'wallet_user')
    list_filter = ('asset', 'change_type', 'created_at', 'wallet__user__membership_level', 'wallet__user__status')
    search_fields = ('wallet__user__username', 'wallet__user__phone', 'wallet__user__invite_code', 'wallet__id', 'change_type')
    readonly_fields = ('wallet', 'asset', 'amount', 'before_balance', 'after_balance', 'change_type', 'created_at', 'remark')

    def wallet_user(self, obj):
        return obj.wallet.user.username
    wallet_user.short_description = '用户名'
    wallet_user.admin_order_field = 'wallet__user__username'

    def wallet_id(self, obj):
        return obj.wallet_id
    wallet_id.short_description = '钱包ID'
    wallet_id.admin_order_field = 'wallet__id'

    def wallet_type(self, obj):
        return obj.get_asset_display()
    wallet_type.short_description = '币种'
    wallet_type.admin_order_field = 'asset'
