"""
对外 HTTP 接口清单（单一数据源）。

新增或修改路由时请务必同步更新本文件中的 `PUBLIC_ENDPOINTS`，否则：
- `GET /api/v1/docs/` 的机器可读列表会不准
- HTML 文档页末尾「接口速查」表会不准

写回 Markdown 文件（可选，便于把仓库里的 taskhub_api.md 一并提交）：

    python manage.py sync_taskhub_api_docs
"""

from __future__ import annotations

import re
from dataclasses import dataclass


API_PREFIX = "/api/v1"


@dataclass(frozen=True)
class PublicEndpoint:
    """对外暴露的一条或多条 HTTP 方法 + 相对 path（与 api_urls.py 中 path() 一致）。"""

    methods: tuple[str, ...]
    path_pattern: str
    description: str
    auth: bool = False


def doc_url_path(path_pattern: str) -> str:
    """将 Django path 转为文档中的路径（含前缀、占位符）。"""
    tail = path_pattern
    if not tail.startswith("/"):
        tail = "/" + tail
    full = API_PREFIX.rstrip("/") + tail.replace("//", "/")
    full = re.sub(r"<int:(\w+)>", r"{\1}", full)
    full = re.sub(r"<str:(\w+)>", r"{\1}", full)
    full = re.sub(r"<uuid:(\w+)>", r"{\1}", full)
    return full


def build_quickref_markdown() -> str:
    """生成「接口速查」Markdown 片段（含二级标题）。"""
    lines = [
        "## 9. 接口速查（自动生成）",
        "",
        "> 数据源：`taskhub/api_endpoints.py`。开放 HTML 文档页会附带本表最新内容。",
        "> 若需把本表写进仓库中的 `docs/taskhub_api.md`，请执行：`python manage.py sync_taskhub_api_docs`",
        "",
        "| 方法 | 路径 | 说明 | 需登录 |",
        "| --- | --- | --- | --- |",
    ]
    for ep in PUBLIC_ENDPOINTS:
        methods = " / ".join(ep.methods)
        path = doc_url_path(ep.path_pattern)
        auth_cell = "是" if ep.auth else "否"
        lines.append(f"| {methods} | `{path}` | {ep.description} | {auth_cell} |")
    return "\n".join(lines)


def get_endpoints_for_public_json() -> list[dict]:
    """供 `GET /api/v1/docs/` 使用：与 `PUBLIC_ENDPOINTS` 一一对应（同路径不同方法各占一行）。"""
    return [
        {
            "method": " / ".join(ep.methods),
            "path": doc_url_path(ep.path_pattern),
            "desc": ep.description,
            "auth": ep.auth,
        }
        for ep in PUBLIC_ENDPOINTS
    ]


# 与 taskhub/api_urls.py 保持同步（新增接口时改这里 + 视图 + 下文手写说明章节）
PUBLIC_ENDPOINTS: tuple[PublicEndpoint, ...] = (
    PublicEndpoint(("GET",), "health/", "服务健康检查", False),
    PublicEndpoint(("GET",), "docs/", "接口目录（JSON）", False),
    PublicEndpoint(("POST",), "auth/register/", "用户注册并返回 token", False),
    PublicEndpoint(("POST",), "auth/login/", "用户登录并返回 token", False),
    PublicEndpoint(
        ("GET", "POST"),
        "auth/telegram/",
        "Telegram 登录：POST init_data；可选 include_home 同包 me/home 数据；GET 说明；另见 POST /api/auth/telegram/",
        False,
    ),
    PublicEndpoint(
        ("GET", "POST"),
        "telegram/miniapp-login/",
        "Telegram 登录别名，与 auth/telegram/ 相同",
        False,
    ),
    PublicEndpoint(("POST",), "auth/logout/", "退出登录", True),
    PublicEndpoint(("GET",), "me/home/", "首页聚合（用户/钱包/累计收益/签到周历）", True),
    PublicEndpoint(("GET",), "me/center/", "个人中心聚合（等级/排名/最近收益/提现规则/外链/含 check_in）", True),
    PublicEndpoint(("GET",), "me/rewards/ledger/", "收益与账单明细（钱包账变分页；summary 为累计入账）", True),
    PublicEndpoint(
        ("GET", "POST"),
        "me/withdrawals/",
        "提现：GET 记录与汇总；POST 发起（扣 USDT、BEP20 地址）",
        True,
    ),
    PublicEndpoint(("GET",), "me/bindings/accounts/", "账号管理：各平台绑定状态与开放必做绑定任务", True),
    PublicEndpoint(
        ("GET", "PATCH"),
        "me/settings/notifications/",
        "通知设置（占位，PATCH 暂未持久化）",
        True,
    ),
    PublicEndpoint(
        ("GET", "POST"),
        "me/check-in/",
        "签到：GET 周历+规则；POST 今日签到（发奖，data 含 last_granted）",
        True,
    ),
    PublicEndpoint(
        ("POST",),
        "me/check-in/make-up/",
        "补签：body.date；先扣 makeup TH，再发与签到相同奖励；data 可有 last_spent/last_granted",
        True,
    ),
    PublicEndpoint(("GET",), "me/profile/", "当前登录用户信息", True),
    PublicEndpoint(("GET",), "categories/", "任务分类列表", False),
    PublicEndpoint(
        ("GET",),
        "guides/categories/",
        "新手指南：分类 Tab（GuideCategory + 兼容旧 category_key；含虚拟「全部」）",
        False,
    ),
    PublicEndpoint(
        ("GET",),
        "guides/featured/",
        "新手指南：置顶大卡/首条推荐（Announcement post_type=newbie_guide）",
        False,
    ),
    PublicEndpoint(
        ("GET",),
        "guides/",
        "新手指南：列表（category_slug=外键 slug 或旧 key；guide_type；分页；正文在详情）",
        False,
    ),
    PublicEndpoint(
        ("GET",),
        "guides/<int:pk>/",
        "新手指南：详情（body=富文本 HTML；video_url 优先本地上传地址）",
        False,
    ),
    PublicEndpoint(
        ("GET",),
        "tasks/mandatory/",
        "首页必做（open+is_mandatory）；仅已录用且已结奖/无奖励时对当前用户隐藏",
        False,
    ),
    PublicEndpoint(
        ("GET",),
        "tasks/center/",
        "任务中心：分类 Tab + 必做 + 可用；必做区剔除规则同 tasks/mandatory/",
        False,
    ),
    PublicEndpoint(("GET",), "tasks/", "任务列表（分页、筛选）", False),
    PublicEndpoint(("POST",), "tasks/", "发布任务", True),
    PublicEndpoint(("GET",), "tasks/<int:task_id>/", "任务详情", False),
    PublicEndpoint(("PATCH",), "tasks/<int:task_id>/", "更新任务（发布人）", True),
    PublicEndpoint(("POST",), "tasks/<int:task_id>/apply/", "报名任务", True),
    PublicEndpoint(
        ("POST",),
        "me/applications/<int:application_id>/verify-twitter/",
        "Twitter 绑定类：站外转发/关注后自动校验并录用（需 TWITTER_BEARER_TOKEN）",
        True,
    ),
    PublicEndpoint(
        ("POST",),
        "me/applications/<int:application_id>/verify-youtube/",
        "YouTube 绑定类：简介含 youtube_proof_link 时拉取 about 页校验后自动录用",
        True,
    ),
    PublicEndpoint(
        ("POST",),
        "me/applications/<int:application_id>/verify-instagram/",
        "Instagram 绑定：含证明链接时仅 Apify 校验（须配 APIFY_API_TOKEN）",
        True,
    ),
    PublicEndpoint(
        ("POST",),
        "me/applications/<int:application_id>/verify-tiktok/",
        "TikTok 绑定：转发指定视频后 Apify 拉 Reposts 校验（须配 APIFY_API_TOKEN，默认 clockworks/tiktok-scraper）",
        True,
    ),
    PublicEndpoint(
        ("POST",),
        "me/applications/<int:application_id>/verify-telegram-group/",
        "加入 Telegram 群任务：Bot getChatMember 校验已入群（须 TELEGRAM_BOT_TOKEN + 任务配置 telegram_chat_id）",
        True,
    ),
    PublicEndpoint(("GET",), "tasks/<int:task_id>/applications/", "发布人查看报名列表", True),
    PublicEndpoint(("PATCH", "POST"), "applications/<int:application_id>/", "发布人审核报名", True),
    PublicEndpoint(("GET",), "me/published-tasks/", "我发布的任务", True),
    PublicEndpoint(("GET",), "me/applied-tasks/", "我报名的任务", True),
    PublicEndpoint(
        ("GET",),
        "me/task-records/",
        "任务记录：分页 + record_status 筛选（与 Tab 进行中/审核中/已完成/已失效 对齐）",
        True,
    ),
)


QUICKREF_MARKERS = ("<!-- API_QUICKREF_BEGIN -->", "<!-- API_QUICKREF_END -->")


def merge_markdown_with_quickref(markdown_source: str) -> str:
    """在文档中插入或替换速查表区块（由 BEGIN/END 标记包围）。"""
    begin, end = QUICKREF_MARKERS
    inner = build_quickref_markdown()
    if begin in markdown_source and end in markdown_source:
        pre, rest = markdown_source.split(begin, 1)
        _, post = rest.split(end, 1)
        return pre.rstrip() + "\n\n" + begin + "\n" + inner + "\n" + end + "\n" + post.lstrip()
    return markdown_source.rstrip() + "\n\n" + begin + "\n" + inner + "\n" + end + "\n"
