"""
个人中心：聚合页、收益账本、提现申请/记录、账号绑定列表。
"""

from __future__ import annotations

import datetime as dt
import logging
import re
from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings
from django.db import transaction
from django.db.utils import OperationalError, ProgrammingError
from django.db.models import Count, Sum
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from users.models import FrontendUser
from wallets.auto_recharge import ensure_user_recharge_address
from wallets.models import RechargeNetworkConfig, RechargeRequest, Transaction, Wallet, WithdrawalRequest

from .api_views import (
    api_error,
    api_response,
    binding_verify_action,
    parse_json_body,
    parse_positive_int,
    require_api_login,
    serialize_user,
)
from .miniapp_api import _check_in_week_payload, _stats_for_user
from .models import MembershipLevelConfig, OnlineFeedback, Task, TaskApplication
from .referral_rewards import grant_membership_purchase_referral_rewards

_MONEY_QUANT = Decimal("0.01")
_LEVEL_EXP_CAP = 5

_LEDGER_LABELS = {
    "task_reward": "任务奖励",
    "reward": "推荐奖励",
    "check_in": "每日签到",
    "check_in_makeup": "补签奖励",
    "check_in_makeup_cost": "补签消耗",
    "cost": "消费",
    "withdraw": "提现",
    "recharge": "充值",
    "adjust": "调账",
    "admin_adjust": "后台拨币",
}

_LEDGER_EXCLUDE_TYPES = frozenset({"admin_adjust", "recharge", "withdraw"})

_PLATFORM_ORDER = (
    Task.BINDING_TWITTER,
    Task.BINDING_YOUTUBE,
    Task.BINDING_INSTAGRAM,
    Task.BINDING_TIKTOK,
    Task.BINDING_TELEGRAM,
)

_PLATFORM_LABELS = dict(Task.BINDING_PLATFORM_CHOICES)
logger = logging.getLogger(__name__)

_RECHARGE_CONFIG_FIELDS = (
    ("token_contract_address", "USDT 合约地址"),
    ("rpc_endpoint", "RPC / API 地址"),
    ("master_mnemonic", "HD 主助记词"),
    ("collector_address", "手续费钱包地址"),
    ("collector_private_key", "手续费钱包私钥"),
    ("sweep_destination_address", "归集目标地址"),
)


def _is_th_transaction(tx: Transaction) -> bool:
    return getattr(tx, "asset", Transaction.ASSET_USDT) == Transaction.ASSET_TH_COIN


def _tx_asset(tx: Transaction) -> str:
    return Transaction.ASSET_TH_COIN if _is_th_transaction(tx) else Transaction.ASSET_USDT


def _tx_asset_label(tx: Transaction) -> str:
    return "TH Coin" if _is_th_transaction(tx) else "USDT"


def _format_amount_for_display(tx: Transaction) -> str:
    a = tx.amount.quantize(_MONEY_QUANT, rounding=ROUND_HALF_UP)
    sign = "+" if a >= 0 else ""
    return f"{sign}{a} {_tx_asset_label(tx)}"


def _ledger_label(tx: Transaction) -> str:
    return _LEDGER_LABELS.get(tx.change_type, tx.get_change_type_display())


def _strip_asset_suffix(text: str) -> str:
    return re.sub(r"(?:[·（(]\s*)?(?:USDT|TH\s*Coin)\s*[）)]?$", "", text, flags=re.IGNORECASE).strip()


def _ledger_detail(tx: Transaction) -> str:
    """面向前端展示的账变原因，避免只显示「消费/奖励」这类过粗的类型。"""
    remark = (tx.remark or "").strip()
    if not remark:
        return _ledger_label(tx)

    membership = re.match(r"^(?:购买|开通|升级)?会员等级\s*(VIP\s*\d+|.+)$", remark, flags=re.IGNORECASE)
    if membership:
        return f"升级 {membership.group(1).strip()}"

    upgraded = re.match(r"^升级\s*(VIP\s*\d+|.+)$", remark, flags=re.IGNORECASE)
    if upgraded:
        return f"升级 {upgraded.group(1).strip()}"

    task_reward = re.match(r"^任务奖励\s*(?:USDT|TH\s*Coin)[：:]\s*(.+)$", remark, flags=re.IGNORECASE)
    if task_reward:
        return f"完成任务：{task_reward.group(1).strip()}"

    checkin = re.match(r"^(每日签到|补签奖励|补签消耗)[：:]\s*(?:USDT|TH\s*Coin)$", remark, flags=re.IGNORECASE)
    if checkin:
        return checkin.group(1)

    return _strip_asset_suffix(remark)


def _rank_position(user: FrontendUser, completed_tasks: int) -> int:
    """按「已录用任务数」排名：人数严格多于当前用户 completed_tasks 的用户数 + 1。"""
    higher = (
        TaskApplication.objects.filter(status=TaskApplication.STATUS_ACCEPTED)
        .values("applicant_id")
        .annotate(n=Count("id"))
        .filter(n__gt=completed_tasks)
        .count()
    )
    return higher + 1


def _level_block(user: FrontendUser, completed_tasks: int) -> dict:
    tier = max(1, int(user.membership_level or 1))
    exp_current = completed_tasks % (_LEVEL_EXP_CAP + 1)
    pct = int(exp_current * 100 / _LEVEL_EXP_CAP) if _LEVEL_EXP_CAP else 0
    return {
        "tier": tier,
        "tier_label": f"Lv.{tier}",
        "title": "新手玩家",
        "exp_current": exp_current,
        "exp_next": _LEVEL_EXP_CAP,
        "progress_percent": min(100, pct),
        "hint": "完成任务可提升等级与经验（示例规则，可后续接入独立经验表）",
    }


def _recent_reward_items(wallet: Wallet, *, limit: int = 8) -> list[dict]:
    qs = _ledger_queryset(wallet, asset=None, days=None)[:limit]
    return [_serialize_ledger_row(tx) for tx in qs]


def _serialize_ledger_row(tx: Transaction) -> dict:
    asset = _tx_asset(tx)
    return {
        "id": tx.id,
        "asset": asset,
        "asset_label": _tx_asset_label(tx),
        "amount": str(tx.amount.quantize(_MONEY_QUANT, rounding=ROUND_HALF_UP)),
        "amount_display": _format_amount_for_display(tx),
        "change_type": tx.change_type,
        "label": _ledger_label(tx),
        "detail": _ledger_detail(tx),
        "remark": tx.remark or "",
        "created_at": tx.created_at.isoformat(),
    }


def _valid_bep20_address(addr: str) -> bool:
    s = addr.strip()
    if s.startswith("0x"):
        s = s[2:]
    return len(s) == 40 and re.fullmatch(r"[0-9a-fA-F]{40}", s) is not None


def _ledger_queryset(wallet: Wallet, *, asset: str | None, days: int | None):
    qs = Transaction.objects.filter(wallet=wallet).exclude(change_type__in=_LEDGER_EXCLUDE_TYPES)
    if asset == "usdt":
        qs = qs.filter(asset=Transaction.ASSET_USDT)
    elif asset == "th_coin":
        qs = qs.filter(asset=Transaction.ASSET_TH_COIN)
    if days is not None and days > 0:
        since = timezone.now() - dt.timedelta(days=days)
        qs = qs.filter(created_at__gte=since)
    return qs.order_by("-created_at")


def _ledger_summary_all_time(wallet: Wallet) -> tuple[Decimal, Decimal]:
    base = Transaction.objects.filter(wallet=wallet).exclude(change_type__in=_LEDGER_EXCLUDE_TYPES)
    usdt_sum = base.filter(amount__gt=0, asset=Transaction.ASSET_USDT).aggregate(s=Sum("amount"))["s"]
    th_sum = base.filter(amount__gt=0, asset=Transaction.ASSET_TH_COIN).aggregate(s=Sum("amount"))["s"]

    def _d(v) -> Decimal:
        if v is None:
            return Decimal("0.00")
        return Decimal(v).quantize(_MONEY_QUANT, rounding=ROUND_HALF_UP)

    return _d(usdt_sum), _d(th_sum)


def _percent_label(rate: Decimal) -> str:
    pct = (Decimal(str(rate)) * Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    text = format(pct.normalize(), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return f"{text}%"


_WITHDRAW_CHAINS = {"ERC20", "TRC20", "BEP20"}


def _normalize_withdraw_chain(raw: str | None) -> str:
    chain = (raw or "BEP20").strip().upper().replace("-", "")
    if chain not in _WITHDRAW_CHAINS:
        raise ValueError("提现网络仅支持 ERC20、TRC20、BEP20")
    return chain


def _valid_evm_address(addr: str) -> bool:
    return re.fullmatch(r"0x[0-9a-fA-F]{40}", addr.strip()) is not None


def _valid_tron_address(addr: str) -> bool:
    return re.fullmatch(r"T[1-9A-HJ-NP-Za-km-z]{33}", addr.strip()) is not None


def _valid_withdraw_address(chain: str, addr: str) -> bool:
    if chain == "TRC20":
        return _valid_tron_address(addr)
    return _valid_evm_address(addr)


def _withdraw_fee_quote(user: FrontendUser, gross: Decimal | None = None) -> dict:
    fallback_fee = Decimal(str(getattr(settings, "WITHDRAW_FEE_USDT", Decimal("0.00")))).quantize(
        _MONEY_QUANT,
        rounding=ROUND_HALF_UP,
    )
    try:
        level_config = MembershipLevelConfig.for_level(user.membership_level)
    except (ProgrammingError, OperationalError):
        level_config = None

    if level_config is None:
        return {
            "fee": fallback_fee,
            "rate": Decimal("0"),
            "rate_label": "固定手续费",
            "mode": "fixed",
            "membership_level_name": None,
        }

    rate = Decimal(str(level_config.withdraw_fee_rate))
    fee = Decimal("0.00") if gross is None else (gross * rate).quantize(_MONEY_QUANT, rounding=ROUND_HALF_UP)
    return {
        "fee": fee,
        "rate": rate,
        "rate_label": _percent_label(rate),
        "mode": "membership_rate",
        "membership_level_name": level_config.name,
    }


def _recharge_network_config_error(network: RechargeNetworkConfig, *, generation_failed: bool = False) -> str | None:
    missing = [label for field, label in _RECHARGE_CONFIG_FIELDS if not str(getattr(network, field, "") or "").strip()]
    if missing:
        return (
            f"{network.display_name} 尚未完成自动充值配置，缺少：{', '.join(missing)}。"
            " 请到后台“资金结算 -> 充值网络配置”补齐后再使用。"
        )
    if generation_failed:
        return (
            f"{network.display_name} 的专属充值地址生成失败，请检查助记词、RPC、手续费钱包和归集目标地址配置是否有效。"
        )
    return None


def _serialize_recharge_network(network: RechargeNetworkConfig, user: FrontendUser | None = None) -> dict:
    address_row = None
    config_error = _recharge_network_config_error(network)
    if user is not None and network.is_auto_ready:
        try:
            address_row = ensure_user_recharge_address(user, network)
        except Exception:
            logger.exception("Failed to ensure recharge address for user=%s network=%s", getattr(user, "id", None), network.pk)
            config_error = _recharge_network_config_error(network, generation_failed=True)
    return {
        "id": network.id,
        "chain": network.chain,
        "display_name": network.display_name,
        "deposit_address": address_row.address if address_row is not None else "",
        "min_amount_usdt": str(network.min_amount_usdt.quantize(_MONEY_QUANT)),
        "confirmations_required": network.confirmations_required,
        "instructions": network.instructions,
        "is_configured": bool(address_row is not None and network.is_auto_ready),
        "address_id": address_row.id if address_row is not None else None,
        "auto_credit": True,
        "auto_sweep": bool(network.sweep_enabled),
        "native_symbol": network.native_symbol,
        "config_error": config_error,
    }


def _serialize_recharge_request(req: RechargeRequest) -> dict:
    return {
        "id": req.id,
        "amount": str(req.amount.quantize(_MONEY_QUANT)),
        "chain": req.chain,
        "deposit_address": req.deposit_address,
        "from_address": req.from_address or "",
        "tx_hash": req.tx_hash,
        "source_type": req.source_type,
        "status": req.status,
        "status_label": req.get_status_display(),
        "reject_reason": req.reject_reason or None,
        "block_number": req.block_number,
        "confirmations": req.confirmations,
        "credited_at": req.credited_at.isoformat() if req.credited_at else None,
        "sweep_status": req.sweep_status,
        "sweep_status_label": req.get_sweep_status_display(),
        "sweep_tx_hash": req.sweep_tx_hash or "",
        "swept_at": req.swept_at.isoformat() if req.swept_at else None,
        "last_error": req.last_error or "",
        "created_at": req.created_at.isoformat(),
        "updated_at": req.updated_at.isoformat(),
        "reviewed_at": req.reviewed_at.isoformat() if req.reviewed_at else None,
    }


def _serialize_feedback(item: OnlineFeedback) -> dict:
    return {
        "id": item.id,
        "title": item.title,
        "content": item.content,
        "contact": item.contact,
        "status": item.status,
        "status_display": item.get_status_display(),
        "admin_reply": item.admin_reply,
        "replied_by": item.replied_by,
        "replied_at": item.replied_at.isoformat() if item.replied_at else None,
        "created_at": item.created_at.isoformat(),
        "updated_at": item.updated_at.isoformat(),
    }


@csrf_exempt
@require_api_login
@require_http_methods(["GET"])
def me_center_api(request):
    """
    个人中心主界面：在 me/home 基础上增加等级/排名、最近收益、提现规则、外链。
    """
    user = request.api_user
    stats = _stats_for_user(user)
    completed = int(stats["completed_tasks_count"])
    rank = _rank_position(user, completed)
    Wallet.objects.get_or_create(user=user)
    wallet = Wallet.objects.get(user=user)

    fee_quote = _withdraw_fee_quote(user)
    min_u = getattr(settings, "WITHDRAW_MIN_USDT", Decimal("2.00"))
    tg_url = getattr(settings, "TELEGRAM_COMMUNITY_URL", "") or ""

    data = {
        "user": serialize_user(user),
        "wallet": {"usdt": stats["usdt_balance"], "th_coin": stats["th_coin_balance"]},
        "stats": {
            "cumulative_earnings_usdt": stats["cumulative_earnings_usdt"],
            "cumulative_earnings_th_coin": stats["cumulative_earnings_th_coin"],
            "completed_tasks_count": completed,
        },
        "level": _level_block(user, completed),
        "rank": {"position": rank, "label": f"全站第 {rank} 名"},
        "recent_rewards": _recent_reward_items(wallet, limit=8),
        "links": {
            "telegram_community": tg_url or None,
        },
        "withdraw": {
            "min_amount_usdt": str(min_u.quantize(_MONEY_QUANT)),
            "fee_usdt": str(fee_quote["fee"].quantize(_MONEY_QUANT)),
            "fee_rate": str(fee_quote["rate"]),
            "fee_rate_label": fee_quote["rate_label"],
            "fee_mode": fee_quote["mode"],
            "membership_level_name": fee_quote["membership_level_name"],
            "chain_default": "BEP20",
            "estimated_arrival_hint": "1–3 个工作日（链上确认后到账）",
        },
        "check_in": _check_in_week_payload(user),
    }
    return api_response(data)


@csrf_exempt
@require_api_login
@require_http_methods(["GET"])
def me_rewards_ledger_api(request):
    """收益/账单明细（钱包账变，不含后台拨币与充值；提现见 me/withdrawals）。"""
    user = request.api_user
    Wallet.objects.get_or_create(user=user)
    wallet = Wallet.objects.get(user=user)

    try:
        page = parse_positive_int(request.GET.get("page", 1), "page", minimum=1)
        page_size = parse_positive_int(request.GET.get("page_size", 20), "page_size", minimum=1)
    except ValueError as exc:
        return api_error(str(exc), code=4001, status=400)

    page_size = min(page_size, 50)
    asset = (request.GET.get("asset") or "all").strip().lower()
    if asset not in ("all", "usdt", "th_coin"):
        return api_error("asset 须为 all / usdt / th_coin", code=4001, status=400)

    raw_days = request.GET.get("days")
    days: int | None
    if raw_days in (None, ""):
        days = None
    else:
        try:
            days = int(raw_days)
        except (TypeError, ValueError):
            return api_error("days 须为整数", code=4001, status=400)
        if days < 0:
            return api_error("days 不能为负", code=4001, status=400)

    qs = _ledger_queryset(wallet, asset=asset if asset != "all" else None, days=days)
    total = qs.count()
    offset = (page - 1) * page_size
    rows = list(qs[offset : offset + page_size])

    total_usdt, total_th = _ledger_summary_all_time(wallet)

    return api_response(
        {
            "summary": {
                "total_usdt": str(total_usdt),
                "total_th_coin": str(total_th),
            },
            "items": [_serialize_ledger_row(tx) for tx in rows],
            "pagination": {"page": page, "page_size": page_size, "total": total},
        }
    )


@csrf_exempt
@require_api_login
@require_http_methods(["GET", "POST"])
def me_withdrawals_api(request):
    """提现记录 GET；发起提现 POST（扣 USDT、生成处理中单）。"""
    user = request.api_user
    Wallet.objects.get_or_create(user=user)

    if request.method == "GET":
        try:
            page = parse_positive_int(request.GET.get("page", 1), "page", minimum=1)
            page_size = parse_positive_int(request.GET.get("page_size", 20), "page_size", minimum=1)
        except ValueError as exc:
            return api_error(str(exc), code=4001, status=400)

        page_size = min(page_size, 50)
        raw_days = request.GET.get("days", "30")
        try:
            days = int(raw_days)
        except (TypeError, ValueError):
            return api_error("days 须为整数", code=4001, status=400)
        if days < 0:
            return api_error("days 不能为负", code=4001, status=400)

        since = timezone.now() - dt.timedelta(days=days) if days > 0 else None
        base = WithdrawalRequest.objects.filter(user=user)
        if since:
            base = base.filter(created_at__gte=since)

        completed_sum = (
            WithdrawalRequest.objects.filter(user=user, status=WithdrawalRequest.STATUS_COMPLETED)
            .aggregate(s=Sum("amount"))["s"]
        )
        total_withdrawn = Decimal(completed_sum or 0).quantize(_MONEY_QUANT, rounding=ROUND_HALF_UP)

        pending_count = WithdrawalRequest.objects.filter(
            user=user,
            status=WithdrawalRequest.STATUS_PROCESSING,
        ).count()

        total = base.count()
        offset = (page - 1) * page_size
        items = list(base.order_by("-created_at")[offset : offset + page_size])

        def _one(w: WithdrawalRequest) -> dict:
            return {
                "id": w.id,
                "amount": str(w.amount.quantize(_MONEY_QUANT)),
                "fee": str(w.fee.quantize(_MONEY_QUANT)),
                "net_amount": str(w.net_amount),
                "chain": w.chain,
                "to_address": w.to_address,
                "status": w.status,
                "reject_reason": w.reject_reason or None,
                "created_at": w.created_at.isoformat(),
                "updated_at": w.updated_at.isoformat(),
            }

        return api_response(
            {
                "summary": {
                    "total_withdrawn_usdt": str(total_withdrawn),
                    "pending_count": pending_count,
                    "window_days": days,
                },
                "items": [_one(w) for w in items],
                "pagination": {"page": page, "page_size": page_size, "total": total},
            }
        )

    # POST
    try:
        body = parse_json_body(request)
    except ValueError as exc:
        return api_error(str(exc), code=4001, status=400)

    raw_amt = body.get("amount")
    to_addr = (body.get("to_address") or body.get("address") or "").strip()
    try:
        chain = _normalize_withdraw_chain(body.get("chain") or body.get("address_type") or body.get("network"))
    except ValueError as exc:
        return api_error(str(exc), code=4085, status=400)

    try:
        gross = Decimal(str(raw_amt)).quantize(_MONEY_QUANT, rounding=ROUND_HALF_UP)
    except Exception:
        return api_error("amount 须为数字", code=4081, status=400)

    fee = _withdraw_fee_quote(user, gross)["fee"]
    min_u = getattr(settings, "WITHDRAW_MIN_USDT", Decimal("2.00")).quantize(
        _MONEY_QUANT, rounding=ROUND_HALF_UP
    )

    if gross < min_u:
        return api_error(f"提现金额不能低于 {min_u} USDT", code=4082, status=400)

    net = (gross - fee).quantize(_MONEY_QUANT, rounding=ROUND_HALF_UP)
    if net <= Decimal("0.00"):
        return api_error("扣除手续费后到账金额须大于 0", code=4083, status=400)

    if not _valid_withdraw_address(chain, to_addr):
        if chain == "TRC20":
            return api_error("收款地址格式无效（TRC20 须为 T 开头的 34 位地址）", code=4084, status=400)
        return api_error(f"收款地址格式无效（{chain} 须为 0x 开头的 42 位地址）", code=4084, status=400)

    with transaction.atomic():
        w = Wallet.objects.select_for_update().get(user=user)
        if w.balance < gross:
            return api_error("USDT 余额不足", code=4080, status=400)

        old_b = w.balance
        new_b = (old_b - gross).quantize(_MONEY_QUANT, rounding=ROUND_HALF_UP)
        tx_row = Transaction.objects.create(
            wallet=w,
            asset=Transaction.ASSET_USDT,
            amount=-gross,
            before_balance=old_b,
            after_balance=new_b,
            change_type="withdraw",
            remark=f"提现 {chain} → {to_addr[:10]}…{to_addr[-6:]}",
        )
        w.balance = new_b
        w.save(create_transaction=False)

        req = WithdrawalRequest.objects.create(
            user=user,
            amount=gross,
            fee=fee,
            chain=chain,
            to_address=to_addr,
            status=WithdrawalRequest.STATUS_PROCESSING,
            debit_transaction=tx_row,
        )

    return api_response(
        {
            "withdrawal": {
                "id": req.id,
                "amount": str(req.amount),
                "fee": str(req.fee),
                "net_amount": str(req.net_amount),
                "chain": req.chain,
                "to_address": req.to_address,
                "status": req.status,
                "created_at": req.created_at.isoformat(),
            }
        },
        message="提现申请已提交",
    )


@csrf_exempt
@require_api_login
@require_http_methods(["GET", "POST"])
def me_recharges_api(request):
    """USDT 自动充值：展示用户专属地址与自动到账记录。"""
    user = request.api_user
    Wallet.objects.get_or_create(user=user)

    if request.method == "GET":
        try:
            page = parse_positive_int(request.GET.get("page", 1), "page", minimum=1)
            page_size = parse_positive_int(request.GET.get("page_size", 20), "page_size", minimum=1)
        except ValueError as exc:
            return api_error(str(exc), code=4001, status=400)

        page_size = min(page_size, 50)
        networks = list(RechargeNetworkConfig.objects.filter(is_active=True).order_by("sort_order", "id"))
        base = RechargeRequest.objects.filter(user=user).order_by("-created_at")
        total = base.count()
        offset = (page - 1) * page_size
        rows = list(base[offset : offset + page_size])
        return api_response(
            {
                "networks": [_serialize_recharge_network(n, user) for n in networks],
                "items": [_serialize_recharge_request(r) for r in rows],
                "pagination": {"page": page, "page_size": page_size, "total": total},
            }
        )

    try:
        body = parse_json_body(request)
    except ValueError as exc:
        return api_error(str(exc), code=4001, status=400)

    chain = str(body.get("chain") or "").strip().upper()
    if chain not in dict(RechargeNetworkConfig.CHAIN_CHOICES):
        return api_error("chain 须为 TRC20 / ERC20 / BEP20", code=4092, status=400)

    network = RechargeNetworkConfig.objects.filter(chain=chain, is_active=True).first()
    if network is None:
        return api_error("该充值网络暂未开放", code=4095, status=400)
    if str(body.get("tx_hash") or body.get("hash") or "").strip():
        return api_error("当前系统已改为自动到账，无需再提交 TxHash，请直接向专属地址充值。", code=4099, status=400)
    if not network.is_auto_ready:
        return api_error("该充值网络尚未完成自动充值配置，请联系客服。", code=4100, status=400)

    address_row = ensure_user_recharge_address(user, network)
    return api_response(
        {"network": _serialize_recharge_network(network, user), "address_id": address_row.id if address_row else None},
        message="专属充值地址已就绪，请直接转入并等待区块确认自动到账。",
    )


@csrf_exempt
@require_api_login
@require_http_methods(["POST"])
def me_membership_purchase_api(request):
    """用钱包 USDT 余额购买 / 升级会员等级。"""
    user = request.api_user
    try:
        body = parse_json_body(request)
    except ValueError as exc:
        return api_error(str(exc), code=4001, status=400)

    try:
        target_level = int(body.get("level"))
    except (TypeError, ValueError):
        return api_error("level 须为整数", code=4101, status=400)

    level_config = MembershipLevelConfig.objects.filter(level=target_level, is_active=True).first()
    if level_config is None:
        return api_error("会员等级不存在或未启用", code=4102, status=404)

    current_level = int(user.membership_level or 0)
    if target_level <= current_level:
        return api_error("当前会员等级已不低于该等级，无需重复购买", code=4103, status=400)

    fee = Decimal(str(level_config.join_fee_usdt)).quantize(_MONEY_QUANT, rounding=ROUND_HALF_UP)
    referral_rewards: list[dict] = []
    with transaction.atomic():
        Wallet.objects.get_or_create(user=user)
        wallet = Wallet.objects.select_for_update().get(user=user)
        if wallet.balance < fee:
            return api_error("USDT 余额不足，请先充值", code=4104, status=400)

        tx_row = None
        if fee > Decimal("0.00"):
            old_balance = wallet.balance
            new_balance = (old_balance - fee).quantize(_MONEY_QUANT, rounding=ROUND_HALF_UP)
            tx_row = Transaction.objects.create(
                wallet=wallet,
                asset=Transaction.ASSET_USDT,
                amount=-fee,
                before_balance=old_balance,
                after_balance=new_balance,
                change_type="cost",
                remark=f"升级 {level_config.name}"[:250],
            )
            wallet.balance = new_balance
            wallet.save(create_transaction=False)

        FrontendUser.objects.filter(pk=user.pk).update(membership_level=target_level)
        user.membership_level = target_level
        referral_rewards = grant_membership_purchase_referral_rewards(
            purchaser=user,
            purchased_level=level_config,
            purchase_amount=fee,
            source_transaction=tx_row,
        )

    Wallet.objects.get_or_create(user=user)
    wallet = Wallet.objects.get(user=user)
    return api_response(
        {
            "membership": {
                "level": level_config.level,
                "name": level_config.name,
                "join_fee_usdt": str(fee),
            },
            "wallet": {
                "usdt": str(wallet.balance.quantize(_MONEY_QUANT)),
                "th_coin": str(wallet.frozen.quantize(_MONEY_QUANT)),
            },
            "transaction_id": tx_row.id if tx_row else None,
            "referral_rewards": referral_rewards,
            "user": serialize_user(user),
        },
        message="会员购买成功",
    )


def _open_mandatory_binding_task(platform: str) -> Task | None:
    return (
        Task.objects.filter(
            interaction_type=Task.INTERACTION_ACCOUNT_BINDING,
            binding_platform=platform,
            status=Task.STATUS_OPEN,
            is_mandatory=True,
        )
        .order_by("-task_list_order", "-id")
        .first()
    )


@csrf_exempt
@require_api_login
@require_http_methods(["GET"])
def me_bound_accounts_api(request):
    """各平台账号绑定状态：来自已录用报名 + 当前开放必做绑定任务。"""
    user = request.api_user

    rows = []
    for platform in _PLATFORM_ORDER:
        app = (
            TaskApplication.objects.filter(
                applicant=user,
                status=TaskApplication.STATUS_ACCEPTED,
                task__interaction_type=Task.INTERACTION_ACCOUNT_BINDING,
                task__binding_platform=platform,
            )
            .select_related("task")
            .order_by("-decided_at", "-created_at")
            .first()
        )
        open_task = _open_mandatory_binding_task(platform)
        linked_by_telegram_login = platform == Task.BINDING_TELEGRAM and user.telegram_id is not None
        linked = app is not None or linked_by_telegram_login
        display_name = None
        if app and app.bound_username:
            display_name = app.bound_username.strip()
        elif linked_by_telegram_login:
            display_name = f"@{user.telegram_username}" if (user.telegram_username or "").strip() else str(user.telegram_id)
        elif linked:
            display_name = user.username

        reward_hint = None
        if linked_by_telegram_login:
            reward_hint = None
        elif open_task and (open_task.reward_th_coin or Decimal("0")) > Decimal("0"):
            reward_hint = f"+{open_task.reward_th_coin.normalize()} TH"
        elif open_task and (open_task.reward_usdt or Decimal("0")) > Decimal("0"):
            reward_hint = f"+{open_task.reward_usdt.normalize()} USDT"

        verify_suffix = binding_verify_action(open_task) if open_task else None

        rows.append(
            {
                "platform": platform,
                "platform_label": _PLATFORM_LABELS.get(platform, platform),
                "linked": linked,
                "display_name": display_name,
                "bound_username": (app.bound_username if app else display_name) or None,
                "reward_hint": reward_hint,
                "task": (
                    {
                        "id": open_task.id,
                        "title": open_task.title,
                        "reward_usdt": str(open_task.reward_usdt),
                        "reward_th_coin": str(open_task.reward_th_coin),
                        "verify_path_suffix": verify_suffix,
                    }
                    if open_task
                    else None
                ),
            }
        )

    return api_response({"items": rows})


@csrf_exempt
@require_api_login
@require_http_methods(["GET", "POST"])
def me_feedback_api(request):
    """在线反馈：前台提交反馈并查看后台回复。"""
    user = request.api_user

    if request.method == "GET":
        try:
            page = parse_positive_int(request.GET.get("page", 1), "page", minimum=1)
            page_size = parse_positive_int(request.GET.get("page_size", 20), "page_size", minimum=1)
        except ValueError as exc:
            return api_error(str(exc), code=4001, status=400)
        page_size = min(page_size, 50)
        qs = OnlineFeedback.objects.filter(user=user).order_by("-updated_at", "-id")
        total = qs.count()
        offset = (page - 1) * page_size
        rows = list(qs[offset : offset + page_size])
        return api_response(
            {
                "items": [_serialize_feedback(item) for item in rows],
                "pagination": {"page": page, "page_size": page_size, "total": total},
            }
        )

    try:
        body = parse_json_body(request)
    except ValueError as exc:
        return api_error(str(exc), code=4001, status=400)

    title = (body.get("title") or "").strip()
    content = (body.get("content") or "").strip()
    contact = (body.get("contact") or "").strip()

    if not content:
        return api_error("反馈内容不能为空", code=4301, status=400)
    if len(content) > 2000:
        return api_error("反馈内容不能超过 2000 字", code=4302, status=400)
    if not title:
        title = content[:30] or "在线反馈"
    if len(title) > 120:
        return api_error("反馈标题不能超过 120 字", code=4303, status=400)
    if len(contact) > 120:
        return api_error("联系方式不能超过 120 字", code=4304, status=400)

    item = OnlineFeedback.objects.create(user=user, title=title, content=content, contact=contact)
    return api_response({"item": _serialize_feedback(item)}, message="反馈已提交")


@csrf_exempt
@require_api_login
@require_http_methods(["GET", "PATCH"])
def me_notification_settings_api(request):
    """通知设置占位：后续可落库 FrontendUser 字段。"""
    if request.method == "GET":
        return api_response(
            {
                "push_enabled": True,
                "task_reminder": True,
                "withdrawal_notice": True,
            }
        )
    try:
        body = parse_json_body(request)
    except ValueError as exc:
        return api_error(str(exc), code=4001, status=400)

    return api_response(
        {
            "push_enabled": bool(body.get("push_enabled", True)),
            "task_reminder": bool(body.get("task_reminder", True)),
            "withdrawal_notice": bool(body.get("withdrawal_notice", True)),
        },
        message="已保存（当前为占位，未持久化）",
    )
