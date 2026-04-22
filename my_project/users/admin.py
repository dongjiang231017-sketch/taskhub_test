from django.contrib import admin
from django.db.models import Count, Prefetch, Q

from taskhub.models import Task, TaskApplication

from .admin_widgets import binding_modal_trigger
from .models import FrontendUser
from wallets.models import Wallet

class WalletInline(admin.StackedInline):
    model = Wallet
    can_delete = False
    verbose_name = '钱包信息'
    verbose_name_plural = '钱包信息'
    fk_name = 'user'
    fields = ('balance', 'frozen')
    extra = 0
    max_num = 1

@admin.register(FrontendUser)
class FrontendUserAdmin(admin.ModelAdmin):
    class Media:
        css = {
            "all": (
                "users/admin_changelist_members.css",
                "users/admin_binding_modal.css",
            )
        }
        js = ("users/admin_binding_modal.js",)

    # 后台列表显示的字段
    list_display = (
        'id',
        'username',
        'telegram_id',
        'membership_level',
        'task_binding_accounts',
        'wallet_balance',
        'wallet_frozen',
        'invite_code',
        'referrer_display',
        'invited_count_display',
        'status',
        'created_at',
    )
    list_select_related = ('wallet', 'referrer')
    
    # 允许点击进入编辑页的字段
    list_display_links = ('id', 'username')
    
    # 右侧过滤器
    list_filter = ('status', 'membership_level', 'created_at')
    
    # 搜索框支持的字段
    search_fields = ('phone', 'username', 'invite_code', 'telegram_username')
    
    # 在后台编辑时，隐藏加密密码字段，防止管理员乱改导致密码损坏
    exclude = ('password', 'pay_password')
    
    autocomplete_fields = ('referrer',)
    
    # 字段分组显示，让后台更整洁
    fieldsets = (
        ('基本信息', {
            'fields': ('phone', 'username', 'membership_level')
        }),
        (
            'Telegram（Mini App）',
            {
                'fields': ('telegram_id', 'telegram_username'),
                'description': (
                    '未走 Telegram 小程序登录时通常为空。测试「入群校验」前，可将 telegram_id 填为你本人 Telegram 数字 ID（可用 @userinfobot 查询），'
                    '须与真实 Telegram 用户一致，Bot 的 getChatMember 才能判你在群内；不要填随机数。'
                    '正式环境建议至少用 Mini App 登录一次以自动写入。'
                ),
            },
        ),
        (
            '邀请关系',
            {
                'fields': ('invite_code', 'referrer', 'invited_count_summary'),
                'description': '「直邀人数」为下级中账号启用（status=true）的人数，与全站邀请榜接口统计口径一致。',
            },
        ),
        ('账号状态', {
            'fields': ('status', 'created_at')
        }),
    )
    
    # 只读字段
    readonly_fields = ('invite_code', 'created_at', 'invited_count_summary')
    
    # 内嵌钱包信息，直接在用户编辑页面修改余额
    inlines = (WalletInline,)

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        qs = qs.annotate(
            invited_count=Count("children", filter=Q(children__status=True)),
        )
        return qs.prefetch_related(
            Prefetch(
                "task_applications",
                queryset=TaskApplication.objects.select_related("task").order_by("-created_at"),
            )
        )

    @admin.display(description="任务绑定账号")
    def task_binding_accounts(self, obj):
        """列表中不直接展示账号，点击按钮在弹窗中查看。含会员资料里的 Telegram ID。"""
        rows = []
        if obj.telegram_id is not None:
            acc = str(obj.telegram_id)
            un = (obj.telegram_username or "").strip()
            if un:
                acc = f"{acc}（@{un}）"
            rows.append({"platform": "Telegram（用户资料）", "account": acc})
        for app in obj.task_applications.all():
            bu = (app.bound_username or "").strip()
            if not bu:
                continue
            task = app.task
            if task.interaction_type == Task.INTERACTION_ACCOUNT_BINDING and task.binding_platform:
                label = task.get_binding_platform_display()
            else:
                label = task.get_interaction_type_display() if task.interaction_type else "任务"
            rows.append({"platform": label, "account": bu})
        if not rows:
            return "—"
        return binding_modal_trigger(rows, label="已绑定 {}".format(len(rows)))

    def wallet_balance(self, obj):
        wallet = getattr(obj, 'wallet', None)
        return wallet.balance if wallet else '暂无'
    wallet_balance.short_description = 'USDT'
    wallet_balance.admin_order_field = 'wallet__balance'

    def wallet_frozen(self, obj):
        wallet = getattr(obj, 'wallet', None)
        return wallet.frozen if wallet else '暂无'
    wallet_frozen.short_description = 'TH Coin'
    wallet_frozen.admin_order_field = 'wallet__frozen'

    @admin.display(description="推荐人", ordering="referrer__username")
    def referrer_display(self, obj):
        r = obj.referrer
        if not r:
            return "—"
        extra = f" @{r.telegram_username}" if (r.telegram_username or "").strip() else ""
        return f"{r.username}{extra} (#{r.id})"

    @admin.display(description="直邀人数", ordering="invited_count")
    def invited_count_display(self, obj):
        """与 GET /api/v1/rankings/invite-leaderboard/ 口径一致：启用下级人数。"""
        return getattr(obj, "invited_count", 0) or 0

    @admin.display(description="直邀人数（启用下级）")
    def invited_count_summary(self, obj):
        if not obj.pk:
            return "—（保存后显示）"
        n = getattr(obj, "invited_count", None)
        if n is None:
            n = FrontendUser.objects.filter(referrer=obj, status=True).count()
        return str(n)