"""
TaskFlow 首页相关接口：Telegram 登录、首页聚合、必做任务列表、签到。
"""

from __future__ import annotations

import datetime as dt
import secrets
from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from users.models import FrontendUser
from wallets.models import Transaction, Wallet

from .integration_config import get_telegram_bot_token
from .models import ApiToken, CheckInConfig, CheckInRecord, TaskApplication
from .telegram_auth import validate_webapp_init_data

from .api_views import (
    api_error,
    api_response,
    build_mandatory_task_items,
    get_optional_api_user,
    parse_json_body,
    require_api_login,
    serialize_user,
)


def _local_today():
    return timezone.localdate()


def _week_range_for_date(d: dt.date) -> tuple[dt.date, dt.date]:
    """周一为一周起点（与 Python weekday 一致：周一 0）。"""
    monday = d - dt.timedelta(days=d.weekday())
    sunday = monday + dt.timedelta(days=6)
    return monday, sunday


def _stats_for_user(user: FrontendUser) -> dict:
    wallet = getattr(user, "wallet", None)
    usdt_balance = str(wallet.balance) if wallet else "0.00"
    th_balance = str(wallet.frozen) if wallet else "0.00"

    if wallet:
        base_q = Transaction.objects.filter(wallet=wallet)
        usdt_inc = base_q.filter(amount__gt=0).exclude(remark__icontains="TH Coin").aggregate(s=Sum("amount"))["s"]
        th_inc = base_q.filter(amount__gt=0, remark__icontains="TH Coin").aggregate(s=Sum("amount"))["s"]
    else:
        usdt_inc = th_inc = None

    def _sum_dec(v) -> Decimal:
        if v is None:
            return Decimal("0.00")
        return Decimal(v)

    cumulative_usdt = str(_sum_dec(usdt_inc).quantize(Decimal("0.01")))
    cumulative_th = str(_sum_dec(th_inc).quantize(Decimal("0.01")))

    completed_tasks = TaskApplication.objects.filter(
        applicant=user,
        status=TaskApplication.STATUS_ACCEPTED,
    ).count()

    return {
        "usdt_balance": usdt_balance,
        "th_coin_balance": th_balance,
        "cumulative_earnings_usdt": cumulative_usdt,
        "cumulative_earnings_th_coin": cumulative_th,
        "completed_tasks_count": completed_tasks,
    }


def _checkin_config_rewards(cfg: CheckInConfig) -> dict:
    return {
        "daily_reward_usdt": str(cfg.daily_reward_usdt),
        "daily_reward_th_coin": str(cfg.daily_reward_th_coin),
        "makeup_cost_th_coin": str(cfg.makeup_cost_th_coin),
        "weekly_makeup_limit": int(cfg.weekly_makeup_limit),
    }


def _grant_checkin_rewards(wallet: Wallet, cfg: CheckInConfig, *, makeup: bool = False) -> dict:
    """按后台配置发放签到奖励（正常签到与补签同一套金额）；无奖励则跳过。"""
    granted = {"usdt": "0", "th_coin": "0"}
    ru, rt = cfg.daily_reward_usdt, cfg.daily_reward_th_coin
    if ru <= Decimal("0") and rt <= Decimal("0"):
        return granted

    old_b, old_f = wallet.balance, wallet.frozen
    new_b = old_b + max(ru, Decimal("0"))
    new_f = old_f + max(rt, Decimal("0"))

    usdt_remark = "补签奖励：USDT" if makeup else "每日签到：USDT"
    th_remark = "补签奖励：TH Coin" if makeup else "每日签到：TH Coin"

    ct = "check_in_makeup" if makeup else "check_in"
    if ru > 0:
        Transaction.objects.create(
            wallet=wallet,
            amount=ru,
            before_balance=old_b,
            after_balance=new_b,
            change_type=ct,
            remark=usdt_remark,
        )
    if rt > 0:
        Transaction.objects.create(
            wallet=wallet,
            amount=rt,
            before_balance=old_f,
            after_balance=new_f,
            change_type=ct,
            remark=th_remark,
        )
    wallet.balance = new_b
    wallet.frozen = new_f
    wallet.save(create_transaction=False)
    if ru > 0:
        granted["usdt"] = str(ru)
    if rt > 0:
        granted["th_coin"] = str(rt)
    return granted


def _deduct_makeup_th_cost(wallet: Wallet, cost: Decimal) -> None:
    if cost <= Decimal("0"):
        return
    old_f = wallet.frozen
    new_f = old_f - cost
    Transaction.objects.create(
        wallet=wallet,
        amount=-cost,
        before_balance=old_f,
        after_balance=new_f,
        change_type="check_in_makeup_cost",
        remark="补签消耗：TH Coin",
    )
    wallet.frozen = new_f
    wallet.save(create_transaction=False)


def _check_in_week_payload(user: FrontendUser) -> dict:
    cfg = CheckInConfig.get()
    today = _local_today()
    monday, sunday = _week_range_for_date(today)
    checked_dates = set(
        CheckInRecord.objects.filter(user=user, on_date__gte=monday, on_date__lte=sunday).values_list(
            "on_date", flat=True
        )
    )
    makeups_used = CheckInRecord.objects.filter(
        user=user,
        on_date__gte=monday,
        on_date__lte=sunday,
        is_make_up=True,
    ).count()
    limit = max(0, int(cfg.weekly_makeup_limit))
    makeups_remaining = max(0, limit - makeups_used)

    weekday_labels = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
    days = []
    for i in range(7):
        d = monday + dt.timedelta(days=i)
        days.append(
            {
                "date": d.isoformat(),
                "weekday_index": i,
                "weekday_label": weekday_labels[i],
                "checked": d in checked_dates,
                "is_today": d == today,
                "can_make_up": (d < today and d >= monday and d not in checked_dates and makeups_remaining > 0),
            }
        )

    streak = 0
    cursor = today
    while CheckInRecord.objects.filter(user=user, on_date=cursor).exists():
        streak += 1
        cursor -= dt.timedelta(days=1)
        if streak > 400:
            break

    return {
        "today": today.isoformat(),
        "week_start": monday.isoformat(),
        "week_end": sunday.isoformat(),
        "days": days,
        "streak_days": streak,
        "makeups_used_this_week": makeups_used,
        "makeups_remaining_this_week": makeups_remaining,
        "makeups_limit_per_week": limit,
        "config": _checkin_config_rewards(cfg),
    }


@csrf_exempt
@require_http_methods(["GET", "POST"])
def telegram_auth_api(request):
    """
    Telegram Mini App 登录：请求体传 init_data（与 WebApp.initData 一致），
    校验通过后按 telegram_id 查找或创建前台用户并签发 API Token。

    GET 仅返回 JSON 说明（避免误用 GET 打开链接时得到 Django HTML 调试页）。
    兼容路径见 data.paths。
    """
    if request.method == "GET":
        return api_response(
            {
                "methods": ["POST"],
                "content_type": "application/json",
                "paths": [
                    "/api/v1/auth/telegram/",
                    "/api/auth/telegram/",
                    "/api/v1/telegram/miniapp-login/",
                ],
                "body_fields": {
                    "init_data": "与 Telegram.WebApp.initData 一致；也可用驼峰 initData",
                },
            },
            message="请使用 POST 发起 Telegram 登录",
        )

    try:
        body = parse_json_body(request)
    except ValueError as exc:
        return api_error(str(exc), code=4001, status=400)

    init_data = (body.get("init_data") or body.get("initData") or "").strip()
    if not init_data:
        return api_error(
            "init_data 必填：须传 Telegram.WebApp.initData 的完整字符串（带签名）。"
            "仅前端展示 initDataUnsafe / user 无法在后端开户；须在 Telegram 内打开 Mini App 后取 initData，"
            "且 Content-Type 须为 application/json。",
            code=4060,
            status=400,
        )

    bot_token = get_telegram_bot_token()
    if not bot_token:
        return api_error(
            "服务端未配置 TELEGRAM_BOT_TOKEN（后台「第三方集成密钥」或环境变量），无法校验 Telegram 登录，因而无法自动注册",
            code=4061,
            status=503,
        )

    try:
        validated = validate_webapp_init_data(init_data, bot_token)
    except ValueError as exc:
        hint = (
            "（常见原因：initData 已过期请重开 Mini App；或 Mini App 绑定的 Bot 与后台 TELEGRAM_BOT_TOKEN 不是同一个）"
        )
        return api_error(f"{exc}{hint}", code=4062, status=401)

    tg = validated["telegram_user"]
    tid = int(tg["id"])
    tg_username = (tg.get("username") or "").strip() or None
    first = (tg.get("first_name") or "").strip() or "User"

    base_username = (f"tg_{tg_username}" if tg_username else f"tg{tid}")[:44]
    username = base_username
    suffix = 0
    while FrontendUser.objects.filter(username=username).exclude(telegram_id=tid).exists():
        suffix += 1
        username = f"{base_username}_{suffix}"[:50]

    raw_pw = secrets.token_urlsafe(32)

    with transaction.atomic():
        user, created = FrontendUser.objects.get_or_create(
            telegram_id=tid,
            defaults={
                "phone": None,
                "username": username,
                "telegram_username": tg_username,
                "password": raw_pw,
            },
        )
        if created:
            Wallet.objects.get_or_create(user=user)
        else:
            Wallet.objects.get_or_create(user=user)
            if tg_username and user.telegram_username != tg_username:
                user.telegram_username = tg_username
                user.save(update_fields=["telegram_username"])

        if not user.status:
            return api_error("账号已被禁用", code=4063, status=403)

        token = ApiToken.issue_for_user(user)

    payload_user = serialize_user(user)
    payload_user["telegram_first_name"] = first
    return api_response({"token": token.key, "user": payload_user}, message="Telegram 登录成功")


@csrf_exempt
@require_api_login
@require_http_methods(["GET"])
def my_home_api(request):
    """首页聚合：用户信息、钱包、累计收益、完成任务数（可选附带签到摘要）。"""
    user = request.api_user
    stats = _stats_for_user(user)
    data = {
        "user": serialize_user(user),
        "wallet": {"usdt": stats["usdt_balance"], "th_coin": stats["th_coin_balance"]},
        "stats": {
            "cumulative_earnings_usdt": stats["cumulative_earnings_usdt"],
            "cumulative_earnings_th_coin": stats["cumulative_earnings_th_coin"],
            "completed_tasks_count": stats["completed_tasks_count"],
        },
        "check_in": _check_in_week_payload(user),
    }
    return api_response(data)


@csrf_exempt
@require_api_login
@require_http_methods(["GET", "POST"])
def my_check_in_api(request):
    user = request.api_user
    if request.method == "GET":
        return api_response(_check_in_week_payload(user))
    today = _local_today()
    if CheckInRecord.objects.filter(user=user, on_date=today).exists():
        return api_error("今日已签到", code=4070, status=409)
    cfg = CheckInConfig.get()
    with transaction.atomic():
        Wallet.objects.get_or_create(user=user)
        wallet = Wallet.objects.select_for_update().get(user=user)
        granted = _grant_checkin_rewards(wallet, cfg, makeup=False)
        CheckInRecord.objects.create(user=user, on_date=today, is_make_up=False)
    payload = _check_in_week_payload(user)
    payload["last_granted"] = granted
    return api_response(payload, message="签到成功")


@csrf_exempt
@require_api_login
@require_http_methods(["POST"])
def my_check_in_makeup_api(request):
    try:
        body = parse_json_body(request)
    except ValueError as exc:
        return api_error(str(exc), code=4001, status=400)

    raw_date = (body.get("date") or "").strip()
    if not raw_date:
        return api_error("date 必填，格式 YYYY-MM-DD", code=4071, status=400)
    try:
        target = dt.date.fromisoformat(raw_date)
    except ValueError:
        return api_error("date 格式须为 YYYY-MM-DD", code=4072, status=400)

    today = _local_today()
    monday, sunday = _week_range_for_date(today)
    if target >= today:
        return api_error("补签仅支持今天之前的日期", code=4073, status=400)
    if target < monday or target > sunday:
        return api_error("仅支持补签当前自然周（周一至周日）内的日期", code=4074, status=400)
    if CheckInRecord.objects.filter(user=request.api_user, on_date=target).exists():
        return api_error("该日已签到", code=4075, status=409)

    used = CheckInRecord.objects.filter(
        user=request.api_user,
        on_date__gte=monday,
        on_date__lte=sunday,
        is_make_up=True,
    ).count()
    cfg = CheckInConfig.get()
    limit = max(0, int(cfg.weekly_makeup_limit))
    if limit <= 0 or used >= limit:
        return api_error("本周补签次数已用完", code=4076, status=400)

    cost = cfg.makeup_cost_th_coin
    with transaction.atomic():
        Wallet.objects.get_or_create(user=request.api_user)
        wallet = Wallet.objects.select_for_update().get(user=request.api_user)
        if cost > Decimal("0") and wallet.frozen < cost:
            return api_error(
                f"TH Coin 不足，补签需要 {cost} TH Coin",
                code=4077,
                status=400,
            )
        _deduct_makeup_th_cost(wallet, cost)
        granted = _grant_checkin_rewards(wallet, cfg, makeup=True)
        CheckInRecord.objects.create(user=request.api_user, on_date=target, is_make_up=True)

    payload = _check_in_week_payload(request.api_user)
    if cost > 0:
        payload["last_spent"] = {"th_coin": str(cost)}
    if granted.get("usdt") != "0" or granted.get("th_coin") != "0":
        payload["last_granted"] = granted
    return api_response(payload, message="补签成功")


@csrf_exempt
@require_http_methods(["GET"])
def mandatory_tasks_api(request):
    """首页「必做任务」卡片列表：is_mandatory=true 且状态 open。
    当前用户若对该任务已是「已录用」，视为必做已完成，不再返回本条（避免前台仍当待做展示）。
    与 `GET /api/v1/tasks/center/` 中 `mandatory.items` 数据源一致，并含 `platform_key`、`slot_progress_percent` 等卡片字段。
    """
    current_user = get_optional_api_user(request)
    return api_response({"items": build_mandatory_task_items(current_user)})
