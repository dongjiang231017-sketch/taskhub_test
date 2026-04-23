from django.contrib import admin

from .models import Transaction, WithdrawalRequest


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
