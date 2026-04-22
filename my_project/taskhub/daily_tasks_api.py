"""活动页：每日任务接口。"""

from __future__ import annotations

from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from .api_views import api_error, api_response, parse_json_body, require_api_login
from .daily_tasks import build_daily_tasks_payload, claim_daily_task_definition


@csrf_exempt
@require_api_login
@require_http_methods(["GET"])
def daily_tasks_list_api(request):
    """每日任务列表 + 当日进度 + 每档 locked/claimable/claimed。"""
    return api_response(build_daily_tasks_payload(request.api_user))


@csrf_exempt
@require_api_login
@require_http_methods(["POST"])
def daily_tasks_claim_api(request):
    """领取某一档每日任务奖励。body: {\"definition_id\": 1}"""
    try:
        body = parse_json_body(request)
    except ValueError as exc:
        return api_error(str(exc), code=4001, status=400)
    raw = body.get("definition_id")
    try:
        definition_id = int(raw)
    except (TypeError, ValueError):
        return api_error("definition_id 须为整数", code=4080, status=400)

    payload, err, status, code = claim_daily_task_definition(request.api_user, definition_id)
    if err:
        return api_error(err, code=code or 4089, status=status)
    return api_response(payload, message="领取成功")
