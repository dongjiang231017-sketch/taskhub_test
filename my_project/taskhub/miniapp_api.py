"""
TaskFlow 首页相关接口：Telegram 登录、首页聚合、必做任务列表、签到。
"""

from __future__ import annotations

import datetime as dt
import logging
import secrets
from decimal import Decimal

from django.conf import settings
from django.db import DatabaseError, transaction
from django.db.models import Sum
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from users.models import FrontendUser
from wallets.models import Transaction, Wallet

from .integration_config import get_telegram_bot_token
from .locale_prefs import normalize_preferred_language, split_start_payload_language
from .models import ApiToken, CheckInConfig, CheckInRecord, TaskApplication, TelegramStartInvitePending
from .referrals import try_bind_referrer_by_invite_code
from .telegram_auth import validate_webapp_init_data
from .telegram_push import send_checkin_success_message

from .api_views import (
    api_error,
    api_response,
    build_mandatory_task_items,
    get_optional_api_user,
    parse_json_body,
    require_api_login,
    serialize_user,
    touch_frontend_user_last_seen,
)

logger = logging.getLogger(__name__)


def _tg_text_field(tg: dict, *keys: str) -> str:
    """读取 initData.user 字段，兼容 snake_case / camelCase。"""
    for k in keys:
        v = tg.get(k)
        if v is None:
            continue
        t = str(v).strip()
        if t:
            return t
    return ""


def _telegram_display_name(tg: dict) -> str:
    """Telegram 设置页「名字」：first_name + last_name（与客户端展示一致）。"""
    fn = _tg_text_field(tg, "first_name", "firstName")
    ln = _tg_text_field(tg, "last_name", "lastName")
    parts = [p for p in (fn, ln) if p]
    if not parts:
        return ""
    return " ".join(parts).strip()


def _preferred_language_from_tg(tg: dict) -> str | None:
    raw = _tg_text_field(tg, "language_code", "languageCode")
    return normalize_preferred_language(raw)


def _allocate_unique_username(base: str, telegram_id: int, *, exclude_pk: int | None) -> str:
    """exclude_pk 有值时排除该用户（已登录同步）；无值时为新建用户，排除同 telegram_id（尚不存在则等价于全表查重）。"""
    base = (base or "").strip()[:50] or f"tg{telegram_id}"
    candidate = base[:50]
    n = 0
    qs = FrontendUser.objects.all()
    if exclude_pk is not None:
        qs = qs.exclude(pk=exclude_pk)
    else:
        qs = qs.exclude(telegram_id=telegram_id)
    while qs.filter(username=candidate).exists():
        n += 1
        suf = f"_{n}"
        candidate = f"{base[: 50 - len(suf)]}{suf}"
    return candidate


def _sync_site_username_from_telegram(
    user: FrontendUser, tg: dict, tid: int, tg_username: str | None, *, created: bool
) -> None:
    """
    只要 initData 里能拼出非空显示名，就同步到站点 username（老用户也会从 tg_xxx 改过来）。
    若本次无显示名：仅新建用户用 @名 / tg<id> 规则写入。
    """
    disp = _telegram_display_name(tg)
    if disp:
        desired_base = " ".join(disp.split())[:50]
    elif created:
        desired_base = _site_username_base_from_telegram_profile(tg, tid)
    else:
        return
    unique = _allocate_unique_username(desired_base, tid, exclude_pk=user.pk)
    if user.username != unique:
        user.username = unique
        user.save(update_fields=["username"])


def _site_username_fallback_handle(tg_username: str | None, telegram_id: int) -> str:
    """无显示名时：用 @handle（仅字母数字下划线），否则 tg<数字ID>。"""
    if tg_username:
        u = "".join(c for c in tg_username.strip() if c.isalnum() or c == "_").strip("_")
        if u:
            return u[:50]
    return f"tg{telegram_id}"[:50]


def _site_username_base_from_telegram_profile(tg: dict, telegram_id: int) -> str:
    """站点用户名基底：优先 Telegram 显示名，其次 @名，否则 tg<id>。"""
    disp = _telegram_display_name(tg)
    if disp:
        return " ".join(disp.split())[:50]
    un = _tg_text_field(tg, "username", "Username") or None
    return _site_username_fallback_handle(un, telegram_id)


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
        usdt_inc = base_q.filter(amount__gt=0, asset=Transaction.ASSET_USDT).aggregate(s=Sum("amount"))["s"]
        th_inc = base_q.filter(amount__gt=0, asset=Transaction.ASSET_TH_COIN).aggregate(s=Sum("amount"))["s"]
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


def _truthy_flag(value) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def _home_data_for_user(user: FrontendUser) -> dict:
    """与 GET /api/v1/me/home/ 的 data 结构一致（供 Telegram 登录一步拉齐）。"""
    stats = _stats_for_user(user)
    return {
        "user": serialize_user(user),
        "wallet": {"usdt": stats["usdt_balance"], "th_coin": stats["th_coin_balance"]},
        "stats": {
            "cumulative_earnings_usdt": stats["cumulative_earnings_usdt"],
            "cumulative_earnings_th_coin": stats["cumulative_earnings_th_coin"],
            "completed_tasks_count": stats["completed_tasks_count"],
        },
        "check_in": _check_in_week_payload(user),
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
            asset=Transaction.ASSET_USDT,
            amount=ru,
            before_balance=old_b,
            after_balance=new_b,
            change_type=ct,
            remark=usdt_remark,
        )
    if rt > 0:
        Transaction.objects.create(
            wallet=wallet,
            asset=Transaction.ASSET_TH_COIN,
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
        asset=Transaction.ASSET_TH_COIN,
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
                "referrer_note": "用户若先点 t.me/bot?start=ref_… 再打开 Mini App 登录：须已配置 Bot Webhook（POST /api/v1/telegram/webhook/）与 TELEGRAM_WEBHOOK_SECRET，详见文档 §2.5",
                "body_fields": {
                    "init_data": "与 Telegram.WebApp.initData 一致；也可用驼峰 initData",
                    "include_home": "可选 true：登录成功后在同一响应里附带与 GET /api/v1/me/home/ 相同的 home 对象",
                    "invite_code": "可选；与 initData 内 start_param 二选一或同时传，用于绑定推荐人；载荷可为 invite_code，或常见 ref_<TelegramId>（与 https://t.me/Bot?start=ref_… 一致）",
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
    if not isinstance(tg, dict):
        return api_error("init_data 中 user 格式无效", code=4064, status=400)
    tid = int(tg["id"])
    tg_username = (tg.get("username") or "").strip() or None
    first_token = _tg_text_field(tg, "first_name", "firstName") or "User"
    body_language = (
        body.get("preferred_language")
        or body.get("preferredLanguage")
        or body.get("language")
        or body.get("locale")
        or ""
    )

    disp = _telegram_display_name(tg)
    base_for_new = " ".join(disp.split())[:50] if disp else _site_username_base_from_telegram_profile(tg, tid)
    username = _allocate_unique_username(base_for_new, tid, exclude_pk=None)

    raw_pw = secrets.token_urlsafe(32)

    with transaction.atomic():
        pairs = validated.get("parsed_pairs") or {}
        start_param = (pairs.get("start_param") or "").strip()
        start_language, start_bind_payload = split_start_payload_language(start_param)
        preferred_language = (
            normalize_preferred_language(start_language or str(body_language or "").strip())
            or _preferred_language_from_tg(tg)
        )

        user, created = FrontendUser.objects.get_or_create(
            telegram_id=tid,
            defaults={
                "phone": None,
                "username": username,
                "telegram_username": tg_username,
                "preferred_language": preferred_language or FrontendUser._meta.get_field("preferred_language").default,
                "password": raw_pw,
            },
        )
        if created:
            Wallet.objects.get_or_create(user=user)
        else:
            Wallet.objects.get_or_create(user=user)
            update_fields: list[str] = []
            if tg_username and user.telegram_username != tg_username:
                user.telegram_username = tg_username
                update_fields.append("telegram_username")
            if preferred_language and user.preferred_language != preferred_language:
                user.preferred_language = preferred_language
                update_fields.append("preferred_language")
            if update_fields:
                user.save(update_fields=update_fields)
        _sync_site_username_from_telegram(user, tg, tid, tg_username, created=created)

        if not user.status:
            return api_error("账号已被禁用", code=4063, status=403)

        # 推荐关系：initData.start_param / body 邀请码；若无则消费 Webhook 写入的 TelegramStartInvitePending（用户先点 t.me/bot?start=…）
        body_invite = (
            (body.get("invite_code") or body.get("ref") or body.get("inviter_invite_code") or "").strip()
        )
        raw_bind = start_bind_payload or body_invite
        if not raw_bind:
            ttl = int(getattr(settings, "TELEGRAM_START_INVITE_PENDING_TTL_SECONDS", 604800) or 604800)
            cutoff = timezone.now() - dt.timedelta(seconds=ttl)
            pending = None
            try:
                pending = (
                    TelegramStartInvitePending.objects.select_for_update()
                    .filter(telegram_id=tid, updated_at__gte=cutoff)
                    .first()
                )
            except DatabaseError as exc:
                # 常见：未执行 migrate 尚无表 taskhub_telegram_start_invite_pending，不应导致整站 Telegram 登录 500
                logger.warning("TelegramStartInvitePending 查询失败（请执行 migrate）: %s", exc)
            if pending:
                pending_language, pending_bind_payload = split_start_payload_language(pending.start_payload)
                if pending_language and user.preferred_language != pending_language:
                    user.preferred_language = pending_language
                    user.save(update_fields=["preferred_language"])
                raw_bind = pending_bind_payload
                pending.delete()
        if raw_bind:
            try_bind_referrer_by_invite_code(user, raw_bind)

        token = ApiToken.issue_for_user(user)
        touch_frontend_user_last_seen(user.id)

    user.refresh_from_db()
    payload_user = serialize_user(user)
    payload_user["telegram_first_name"] = first_token
    display_name = _telegram_display_name(tg)
    if display_name:
        payload_user["telegram_display_name"] = display_name
    out: dict = {"token": token.key, "user": payload_user}
    if _truthy_flag(body.get("include_home") or body.get("includeHome")):
        out["home"] = _home_data_for_user(user)
    return api_response(out, message="Telegram 登录成功")


@csrf_exempt
@require_api_login
@require_http_methods(["GET"])
def my_home_api(request):
    """首页聚合：用户信息、钱包、累计收益、完成任务数（可选附带签到摘要）。"""
    user = request.api_user
    return api_response(_home_data_for_user(user))


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
    send_checkin_success_message(
        user,
        streak_days=int(payload.get("current_streak_days") or 0),
        granted=granted,
        is_makeup=False,
    )
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
    send_checkin_success_message(
        request.api_user,
        streak_days=int(payload.get("current_streak_days") or 0),
        granted=granted,
        is_makeup=True,
        spent_th_coin=cost,
    )
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
