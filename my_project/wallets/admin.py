from django.contrib import admin

from .models import RechargeNetworkConfig, RechargeRequest, Transaction, WithdrawalRequest


@admin.register(RechargeNetworkConfig)
class RechargeNetworkConfigAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "sort_order",
        "chain",
        "display_name",
        "deposit_address_short",
        "min_amount_usdt",
        "confirmations_required",
        "is_active",
        "updated_at",
    )
    list_filter = ("is_active", "chain")
    search_fields = ("chain", "display_name", "deposit_address")
    ordering = ("sort_order", "id")
    fieldsets = (
        ("网络", {"fields": ("sort_order", "chain", "display_name", "is_active")}),
        ("收款", {"fields": ("deposit_address", "min_amount_usdt", "confirmations_required")}),
        ("说明", {"fields": ("instructions",)}),
        ("系统", {"fields": ("updated_at",)}),
    )
    readonly_fields = ("updated_at",)

    @admin.display(description="收款地址")
    def deposit_address_short(self, obj):
        s = obj.deposit_address or ""
        if not s:
            return "未配置"
        if len(s) <= 24:
            return s
        return f"{s[:12]}…{s[-10:]}"


@admin.register(RechargeRequest)
class RechargeRequestAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "user",
        "amount",
        "chain",
        "tx_hash_short",
        "status",
        "created_at",
        "reviewed_at",
    )
    list_display_links = ("id", "user")
    list_filter = ("status", "chain", "created_at")
    search_fields = ("user__username", "user__phone", "user__invite_code", "tx_hash", "from_address", "deposit_address")
    readonly_fields = (
        "user",
        "amount",
        "chain",
        "deposit_address",
        "from_address",
        "tx_hash",
        "credited_transaction",
        "created_at",
        "updated_at",
        "reviewed_at",
    )
    actions = ("approve_selected", "reject_selected")
    date_hierarchy = "created_at"
    ordering = ("-created_at",)
    list_per_page = 50
    list_select_related = ("user", "credited_transaction")

    fieldsets = (
        ("充值信息", {"fields": ("user", "amount", "chain", "deposit_address", "from_address", "tx_hash")}),
        ("审核", {"fields": ("status", "reject_reason", "credited_transaction", "reviewed_at")}),
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

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if obj.status == RechargeRequest.STATUS_COMPLETED and not obj.credited_transaction_id:
            obj.credit_to_wallet()

    @admin.action(description="审核通过并入账")
    def approve_selected(self, request, queryset):
        count = 0
        for obj in queryset.filter(status=RechargeRequest.STATUS_PENDING):
            obj.credit_to_wallet()
            count += 1
        self.message_user(request, f"已审核入账 {count} 笔充值。")

    @admin.action(description="拒绝所选充值申请")
    def reject_selected(self, request, queryset):
        count = queryset.filter(status=RechargeRequest.STATUS_PENDING).update(status=RechargeRequest.STATUS_REJECTED)
        self.message_user(request, f"已拒绝 {count} 笔充值申请。")


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
