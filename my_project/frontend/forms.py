from django import forms
from django.core.exceptions import ValidationError
from users.models import FrontendUser
from staking.models import StakingProduct


class RegisterForm(forms.Form):
    phone = forms.CharField(max_length=11, label='手机号')
    username = forms.CharField(max_length=50, label='用户名')
    password = forms.CharField(widget=forms.PasswordInput, min_length=6, label='登录密码')
    confirm_password = forms.CharField(widget=forms.PasswordInput, min_length=6, label='确认密码')
    pay_password = forms.CharField(widget=forms.PasswordInput, min_length=6, label='支付密码')
    membership_level = forms.ChoiceField(
        choices=[('1', '普通会员'), ('2', 'VIP会员'), ('3', '超级VIP')],
        label='会员等级',
        initial='1'
    )

    def clean_phone(self):
        phone = self.cleaned_data['phone']
        if FrontendUser.objects.filter(phone=phone).exists():
            raise ValidationError('该手机号已注册')
        return phone

    def clean_username(self):
        username = self.cleaned_data['username']
        if FrontendUser.objects.filter(username=username).exists():
            raise ValidationError('该用户名已被占用')
        return username

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get('password')
        confirm_password = cleaned_data.get('confirm_password')
        if password and confirm_password and password != confirm_password:
            raise ValidationError('两次输入的密码不一致')
        return cleaned_data


class LoginForm(forms.Form):
    phone = forms.CharField(
        max_length=11,
        label='手机号',
        widget=forms.TextInput(attrs={'placeholder': 'Enter your email'})
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={'placeholder': 'Please Enter Password'}),
        label='登录密码'
    )


class ForgotPasswordForm(forms.Form):
    phone = forms.CharField(
        max_length=11,
        label='手机号',
        widget=forms.TextInput(attrs={'placeholder': 'Enter your email'})
    )
    new_password = forms.CharField(
        widget=forms.PasswordInput(attrs={'placeholder': 'Enter new password'}),
        min_length=6,
        label='新密码'
    )
    confirm_password = forms.CharField(
        widget=forms.PasswordInput(attrs={'placeholder': 'Confirm new password'}),
        min_length=6,
        label='确认密码'
    )

    def clean_phone(self):
        phone = self.cleaned_data['phone']
        if not FrontendUser.objects.filter(phone=phone).exists():
            raise ValidationError('手机号未注册')
        return phone

    def clean(self):
        cleaned_data = super().clean()
        new_password = cleaned_data.get('new_password')
        confirm_password = cleaned_data.get('confirm_password')
        if new_password and confirm_password and new_password != confirm_password:
            raise ValidationError('两次输入的密码不一致')
        return cleaned_data


class ProfileForm(forms.Form):
    username = forms.CharField(max_length=50, label='用户名')
    password = forms.CharField(widget=forms.PasswordInput, required=False, label='登录密码（填写则修改）')
    pay_password = forms.CharField(widget=forms.PasswordInput, required=False, label='支付密码（填写则修改）')

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user

    def clean_username(self):
        username = self.cleaned_data['username']
        if FrontendUser.objects.filter(username=username).exclude(pk=self.user.pk).exists():
            raise ValidationError('该用户名已被占用')
        return username


class StakeForm(forms.Form):
    product_id = forms.IntegerField(widget=forms.HiddenInput)
    amount = forms.DecimalField(max_digits=20, decimal_places=2, min_value=0.01, label='质押金额')

    def clean(self):
        cleaned_data = super().clean()
        product_id = cleaned_data.get('product_id')
        amount = cleaned_data.get('amount')
        if product_id and amount:
            try:
                product = StakingProduct.objects.get(pk=product_id, is_active=True)
            except StakingProduct.DoesNotExist:
                raise ValidationError('无效的质押产品')
            if product.min_amount and amount < product.min_amount:
                raise ValidationError(f'质押金额不能低于 {product.min_amount}')
            if product.max_amount and amount > product.max_amount:
                raise ValidationError(f'质押金额不能高于 {product.max_amount}')
        return cleaned_data
