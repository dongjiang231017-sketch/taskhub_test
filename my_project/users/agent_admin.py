from django.contrib import admin
from django.contrib.admin import AdminSite
from django.db.models import Count

from staking.models import StakeRecord
from taskhub.models import (
    CheckInRecord,
    DailyTaskDayClaim,
    InviteAchievementClaim,
    TaskApplication,
    TaskCompletionRecord,
)
from wallets.models import Transaction, Wallet, WithdrawalRequest

from .agent_scope import (
    describe_agent_scope,
    filter_queryset_by_agent_users,
    get_agent_profile_for_request,
)
from .models import FrontendUser


class AgentAdminSite(AdminSite):
    site_header = "TaskHub 代理后台"
    site_title = "代理后台"
    index_title = "伞下数据中心"
    site_url = None

    def has_permission(self, request):
        user = request.user
        if not (user.is_active and user.is_staff):
            return False
        if user.is_superuser:
            return True
        return get_agent_profile_for_request(request) is not None

    def each_context(self, request):
        context = super().each_context(request)
        context["agent_scope_summary"] = describe_agent_scope(request)
        return context

    def index(self, request, extra_context=None):
        extra_context = {"title": describe_agent_scope(request), **(extra_context or {})}
        return super().index(request, extra_context=extra_context)


agent_site = AgentAdminSite(name="agent_admin")


class AgentReadonlyScopedAdmin(admin.ModelAdmin):
    """Read-only admin that automatically filters every model by the agent's umbrella users."""

    user_lookup = None
    list_per_page = 50

    def has_module_permission(self, request):
        return agent_site.has_permission(request)

    def has_view_permission(self, request, obj=None):
        return agent_site.has_permission(request)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def get_actions(self, request):
        return {}

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if self.user_lookup:
            qs = filter_queryset_by_agent_users(request, qs, self.user_lookup)
        return qs


@admin.register(FrontendUser, site=agent_site)
class AgentFrontendUserAdmin(AgentReadonlyScopedAdmin):
    user_lookup = "id"
    list_display = (
        "id",
        "username",
        "telegram_id",
        "membership_level",
        "wallet_balance",
        "wallet_frozen",
        "invite_code",
        "referrer",
        "direct_invited_count",
        "status",
        "created_at",
    )
    list_filter = ("status", "membership_level", "created_at")
    search_fields = ("username", "phone", "invite_code", "telegram_username", "telegram_id")
    list_select_related = ("wallet", "referrer")
    ordering = ("-created_at",)

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(
            direct_invites=Count("children"),
        )

    @admin.display(description="USDT", ordering="wallet__balance")
    def wallet_balance(self, obj):
        wallet = getattr(obj, "wallet", None)
        return wallet.balance if wallet else "暂无"

    @admin.display(description="TH Coin", ordering="wallet__frozen")
    def wallet_frozen(self, obj):
        wallet = getattr(obj, "wallet", None)
        return wallet.frozen if wallet else "暂无"

    @admin.display(description="直邀人数", ordering="direct_invites")
    def direct_invited_count(self, obj):
        return getattr(obj, "direct_invites", 0) or 0


@admin.register(Wallet, site=agent_site)
class AgentWalletAdmin(AgentReadonlyScopedAdmin):
    user_lookup = "user_id"
    list_display = ("id", "user", "balance", "frozen")
    search_fields = ("user__username", "user__phone", "user__invite_code", "id")
    list_select_related = ("user",)
    ordering = ("user_id",)


@admin.register(Transaction, site=agent_site)
class AgentTransactionAdmin(AgentReadonlyScopedAdmin):
    user_lookup = "wallet__user_id"
    list_display = (
        "id",
        "wallet_user",
        "wallet",
        "asset",
        "amount",
        "before_balance",
        "after_balance",
        "change_type",
        "remark",
        "created_at",
    )
    list_filter = ("asset", "change_type", "created_at")
    search_fields = ("wallet__user__username", "wallet__user__phone", "wallet__user__invite_code", "remark")
    list_select_related = ("wallet", "wallet__user")
    ordering = ("-created_at",)

    @admin.display(description="用户", ordering="wallet__user__username")
    def wallet_user(self, obj):
        return obj.wallet.user


@admin.register(WithdrawalRequest, site=agent_site)
class AgentWithdrawalRequestAdmin(AgentReadonlyScopedAdmin):
    user_lookup = "user_id"
    list_display = (
        "id",
        "user",
        "amount",
        "fee",
        "net_amount",
        "chain",
        "to_address",
        "status",
        "created_at",
        "updated_at",
    )
    list_filter = ("status", "chain", "created_at")
    search_fields = ("user__username", "user__phone", "user__invite_code", "to_address", "id")
    list_select_related = ("user",)
    ordering = ("-created_at",)


@admin.register(TaskApplication, site=agent_site)
class AgentTaskApplicationAdmin(AgentReadonlyScopedAdmin):
    user_lookup = "applicant_id"
    list_display = (
        "id",
        "task",
        "applicant",
        "bound_username",
        "quoted_price",
        "status",
        "self_verified_at",
        "created_at",
        "decided_at",
        "reward_paid_at",
    )
    list_filter = ("status", "created_at", "reward_paid_at")
    search_fields = ("task__title", "applicant__username", "applicant__phone", "applicant__invite_code")
    list_select_related = ("task", "applicant")
    ordering = ("-created_at",)


@admin.register(TaskCompletionRecord, site=agent_site)
class AgentTaskCompletionRecordAdmin(AgentTaskApplicationAdmin):
    def get_queryset(self, request):
        return super().get_queryset(request).filter(status=TaskApplication.STATUS_ACCEPTED)


@admin.register(CheckInRecord, site=agent_site)
class AgentCheckInRecordAdmin(AgentReadonlyScopedAdmin):
    user_lookup = "user_id"
    list_display = ("id", "user", "on_date", "is_make_up", "created_at")
    list_filter = ("is_make_up", "on_date")
    search_fields = ("user__username", "user__phone", "user__invite_code")
    list_select_related = ("user",)
    ordering = ("-on_date", "-id")


@admin.register(DailyTaskDayClaim, site=agent_site)
class AgentDailyTaskDayClaimAdmin(AgentReadonlyScopedAdmin):
    user_lookup = "user_id"
    list_display = ("id", "user", "definition", "on_date", "claimed_at")
    list_filter = ("on_date", "definition")
    search_fields = ("user__username", "user__phone", "user__invite_code", "definition__title")
    list_select_related = ("user", "definition")
    ordering = ("-on_date", "-id")


@admin.register(InviteAchievementClaim, site=agent_site)
class AgentInviteAchievementClaimAdmin(AgentReadonlyScopedAdmin):
    user_lookup = "user_id"
    list_display = ("id", "user", "tier", "claimed_at")
    list_filter = ("tier", "claimed_at")
    search_fields = ("user__username", "user__phone", "user__invite_code", "tier__title")
    list_select_related = ("user", "tier")
    ordering = ("-claimed_at",)


@admin.register(StakeRecord, site=agent_site)
class AgentStakeRecordAdmin(AgentReadonlyScopedAdmin):
    user_lookup = "user_id"
    list_display = (
        "id",
        "user",
        "product",
        "amount",
        "annual_rate",
        "status",
        "total_earned",
        "last_settled_at",
        "created_at",
    )
    list_filter = ("status", "product", "created_at")
    search_fields = ("user__username", "user__phone", "user__invite_code", "product__name")
    list_select_related = ("user", "product")
    ordering = ("-created_at",)
