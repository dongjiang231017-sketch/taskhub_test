"""活动页：邀请成就等接口。"""

from __future__ import annotations

from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from .api_views import api_error, api_response, get_optional_api_user, parse_json_body, require_api_login
from .invite_activity import build_invite_activity_rules_payload
from .invite_achievements import build_invite_achievements_payload, claim_invite_achievement_tier


@csrf_exempt
@require_http_methods(["GET"])
def invite_activity_rules_api(request):
    """邀请拉新活动规则：会员等级、二级分佣、团队长扶持，全部来自后台配置。"""
    user = get_optional_api_user(request)
    return api_response(build_invite_activity_rules_payload(user))


@csrf_exempt
@require_api_login
@require_http_methods(["GET"])
def me_invite_achievements_api(request):
    """
    邀请成就列表：后台配置的阶梯 + 当前用户有效邀请人数 + 每档状态（locked/claimable/claimed）。
    """
    data = build_invite_achievements_payload(request.api_user)
    return api_response(data)


@csrf_exempt
@require_api_login
@require_http_methods(["POST"])
def me_invite_achievements_claim_api(request):
    """领取某一档邀请成就奖励。body: {\"tier_id\": 1}"""
    try:
        body = parse_json_body(request)
    except ValueError as exc:
        return api_error(str(exc), code=4001, status=400)
    raw = body.get("tier_id")
    try:
        tier_id = int(raw)
    except (TypeError, ValueError):
        return api_error("tier_id 须为整数", code=4070, status=400)

    payload, err, status, code = claim_invite_achievement_tier(request.api_user, tier_id)
    if err:
        return api_error(err, code=code or 4079, status=status)
    return api_response(payload, message="领取成功")
