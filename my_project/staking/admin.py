from django import forms
from django.contrib import admin
from .models import StakingProduct, StakeRecord


class StakingProductAdminForm(forms.ModelForm):
    class Meta:
        model = StakingProduct
        fields = '__all__'
        widgets = {
            'description': forms.Textarea(attrs={'rows': 10, 'cols': 80}),
        }


@admin.register(StakingProduct)
class StakingProductAdmin(admin.ModelAdmin):
    form = StakingProductAdminForm
    list_display = ('id', 'name', 'annual_rate', 'min_amount', 'max_amount', 'duration_days', 'is_active', 'created_at')
    list_filter = ('is_active',)
    search_fields = ('name',)
    readonly_fields = ('created_at',)
    fieldsets = (
        ('产品信息', {
            'fields': ('name', 'annual_rate', 'min_amount', 'max_amount', 'duration_days', 'description', 'image', 'is_active')
        }),
    )

    class Media:
        js = (
            'https://cdn.jsdelivr.net/npm/tinymce@6/tinymce.min.js',
            'staking/js/tinymce-init.js',
        )


@admin.register(StakeRecord)
class StakeRecordAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'product', 'amount', 'annual_rate', 'status', 'total_earned', 'last_settled_at', 'created_at')
    list_filter = ('status', 'product', 'created_at')
    search_fields = ('user__username', 'user__phone', 'product__name')
    readonly_fields = ('total_earned', 'last_settled_at', 'created_at', 'updated_at')
    fieldsets = (
        ('质押信息', {
            'fields': ('user', 'product', 'amount', 'annual_rate', 'status')
        }),
        ('结算信息', {
            'fields': ('total_earned', 'last_settled_at')
        }),
    )
