import json
from decimal import Decimal
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.db import transaction
from django.http import HttpResponseRedirect
from users.models import FrontendUser
from announcements.models import Announcement
from staking.models import StakingProduct, StakeRecord
from wallets.models import Wallet, Transaction
from .forms import (
    RegisterForm,
    LoginForm,
    ForgotPasswordForm,
    ProfileForm,
    StakeForm,
)

COIN_LIST = [
    {'symbol': 'BTC', 'name': '比特币', 'price': 39000.00, 'change': 1.52},
    {'symbol': 'ETH', 'name': '以太坊', 'price': 2800.00, 'change': -0.62},
    {'symbol': 'USDT', 'name': '泰达币', 'price': 1.00, 'change': 0.01},
    {'symbol': 'BNB', 'name': '币安币', 'price': 320.00, 'change': 0.98},
    {'symbol': 'SOL', 'name': '索拉纳', 'price': 85.00, 'change': 2.14},
    {'symbol': 'ADA', 'name': '卡尔达诺', 'price': 0.48, 'change': -0.78},
    {'symbol': 'XRP', 'name': '瑞波币', 'price': 0.62, 'change': 0.37},
    {'symbol': 'DOGE', 'name': '狗狗币', 'price': 0.13, 'change': -1.10},
    {'symbol': 'DOT', 'name': '波卡', 'price': 6.80, 'change': 0.25},
    {'symbol': 'LTC', 'name': '莱特币', 'price': 85.50, 'change': 1.10},
]


def get_current_user(request):
    user_id = request.session.get('frontend_user_id')
    if not user_id:
        return None
    try:
        return FrontendUser.objects.get(pk=user_id)
    except FrontendUser.DoesNotExist:
        return None


def render_with_user(request, template_name, context=None):
    context = context or {}
    context['current_user'] = get_current_user(request)
    return render(request, template_name, context)


def frontend_login_required(view_func):
    def wrapper(request, *args, **kwargs):
        current_user = get_current_user(request)
        if not current_user:
            return redirect('frontend:login')
        request.current_user = current_user
        return view_func(request, *args, **kwargs)
    wrapper.__name__ = view_func.__name__
    return wrapper


@frontend_login_required
def home_view(request):
    announcements = Announcement.objects.filter(is_active=True, publish_at__lte=timezone.now()).order_by('-publish_at')[:5]
    products = StakingProduct.objects.filter(is_active=True).order_by('-created_at')[:4]
    return render_with_user(request, 'frontend/home.html', {
        'announcements': announcements,
        'products': products,
        'coins_json': json.dumps(COIN_LIST),
    })


@frontend_login_required
def announcement_list_view(request):
    announcements = Announcement.objects.filter(is_active=True, publish_at__lte=timezone.now()).order_by('-publish_at')
    return render_with_user(request, 'frontend/announcements.html', {'announcements': announcements})


@frontend_login_required
def announcement_detail_view(request, pk):
    announcement = get_object_or_404(Announcement, pk=pk, is_active=True)
    return render_with_user(request, 'frontend/announcement_detail.html', {'announcement': announcement})


def register_view(request):
    if request.method == 'POST':
        form = RegisterForm(request.POST)
        if form.is_valid():
            cleaned = form.cleaned_data
            user = FrontendUser(
                phone=cleaned['phone'],
                username=cleaned['username'],
                password=cleaned['password'],
                pay_password=cleaned['pay_password'],
                membership_level=int(cleaned['membership_level']),
            )
            user.save()
            Wallet.objects.create(user=user)
            request.session['frontend_user_id'] = user.pk
            return redirect('frontend:home')
    else:
        form = RegisterForm()
    return render_with_user(request, 'frontend/register.html', {'form': form, 'body_class': 'login-layout'})


def login_view(request):
    if request.method == 'POST':
        form = LoginForm(request.POST)
        if form.is_valid():
            phone = form.cleaned_data['phone']
            password = form.cleaned_data['password']
            try:
                user = FrontendUser.objects.get(phone=phone)
            except FrontendUser.DoesNotExist:
                user = None
            if user and user.verify_password(password) and user.status:
                request.session['frontend_user_id'] = user.pk
                return redirect('frontend:home')
            form.add_error(None, '手机号或密码不正确')
    else:
        form = LoginForm()
    return render_with_user(request, 'frontend/login.html', {'form': form, 'body_class': 'login-layout'})


def logout_view(request):
    request.session.pop('frontend_user_id', None)
    return redirect('frontend:login')


def forgot_password_view(request):
    if request.method == 'POST':
        form = ForgotPasswordForm(request.POST)
        if form.is_valid():
            phone = form.cleaned_data['phone']
            new_password = form.cleaned_data['new_password']
            user = FrontendUser.objects.get(phone=phone)
            user.password = new_password
            user.save()
            return redirect('frontend:login')
    else:
        form = ForgotPasswordForm()
    return render_with_user(request, 'frontend/forgot_password.html', {'form': form, 'body_class': 'login-layout'})


@frontend_login_required
def profile_view(request):
    current_user = request.current_user
    if request.method == 'POST':
        form = ProfileForm(request.POST, user=current_user)
        if form.is_valid():
            current_user.username = form.cleaned_data['username']
            password = form.cleaned_data.get('password')
            pay_password = form.cleaned_data.get('pay_password')
            if password:
                current_user.password = password
            if pay_password:
                current_user.pay_password = pay_password
            current_user.save()
            return redirect('frontend:profile')
    else:
        form = ProfileForm(user=current_user, initial={'username': current_user.username})
    return render_with_user(request, 'frontend/profile.html', {'form': form, 'user': current_user})


@frontend_login_required
def wallet_view(request):
    current_user = request.current_user
    wallet, created = Wallet.objects.get_or_create(user=current_user)
    return render_with_user(request, 'frontend/wallet.html', {'wallet': wallet})


@frontend_login_required
def transaction_view(request):
    current_user = request.current_user
    transactions = Transaction.objects.filter(wallet__user=current_user).order_by('-created_at')[:50]
    return render_with_user(request, 'frontend/transactions.html', {'transactions': transactions})


@frontend_login_required
def staking_list_view(request):
    current_user = request.current_user
    products = StakingProduct.objects.filter(is_active=True).order_by('-created_at')
    form = StakeForm()
    return render_with_user(request, 'frontend/staking_list.html', {'products': products, 'form': form})


@frontend_login_required
def stake_create_view(request):
    current_user = request.current_user
    if request.method != 'POST':
        return redirect('frontend:staking_list')
    form = StakeForm(request.POST)
    if form.is_valid():
        product = StakingProduct.objects.get(pk=form.cleaned_data['product_id'], is_active=True)
        amount = form.cleaned_data['amount']
        try:
            with transaction.atomic():
                stake = StakeRecord(
                    user=current_user,
                    product=product,
                    amount=amount,
                    annual_rate=product.annual_rate,
                )
                stake.save()
        except Exception as exc:
            form.add_error(None, str(exc))
            products = StakingProduct.objects.filter(is_active=True).order_by('-created_at')
            return render_with_user(request, 'frontend/staking_list.html', {'products': products, 'form': form})
        return redirect('frontend:stake_records')
    products = StakingProduct.objects.filter(is_active=True).order_by('-created_at')
    return render_with_user(request, 'frontend/staking_list.html', {'products': products, 'form': form})


@frontend_login_required
def stake_record_view(request):
    current_user = request.current_user
    records = StakeRecord.objects.filter(user=current_user).order_by('-created_at')
    return render_with_user(request, 'frontend/stake_records.html', {'records': records})


@frontend_login_required
def release_record_view(request):
    current_user = request.current_user
    records = Transaction.objects.filter(wallet__user=current_user, change_type='reward').order_by('-created_at')[:50]
    return render_with_user(request, 'frontend/release_records.html', {'records': records})
