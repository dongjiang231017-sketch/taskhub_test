"""后台列表「绑定账号」弹窗触发按钮（与静态 JS/CSS 配套）。"""

from __future__ import annotations

import base64
import json
from typing import Any

from django.utils.html import format_html
from django.utils.safestring import mark_safe

# 小号链接/绑定图标（内联 SVG，避免依赖图标字体）
_ICON_SVG = mark_safe(
    '<svg class="th-bind-modal-trigger__svg" viewBox="0 0 24 24" width="16" height="16" '
    'fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">'
    '<path d="M10 13a5 5 0 0 1 7.54.54M14 11a5 5 0 0 0-7.54-.54" stroke="currentColor" stroke-width="1.8" '
    'stroke-linecap="round"/>'
    '<circle cx="7" cy="8" r="2.2" stroke="currentColor" stroke-width="1.6"/>'
    '<circle cx="17" cy="16" r="2.2" stroke="currentColor" stroke-width="1.6"/>'
    "</svg>"
)


def binding_modal_trigger(rows: list[dict[str, Any]], *, label: str) -> str:
    """
    rows: 每项含 platform（可选）、account（弹窗内展示「已绑定」）。
    label: 按钮上主文案，如「已绑定 2」或「已绑定 · 查看」。
    """
    if not rows:
        return "—"
    # ensure_ascii=True：JSON 仅含 ASCII + \uXXXX，Base64 后前端 atob+JSON.parse 无需 UTF-8 二进制解码，避免中文乱码
    payload = base64.b64encode(json.dumps(rows, ensure_ascii=True, separators=(",", ":")).encode("ascii")).decode(
        "ascii"
    )
    return format_html(
        '<button type="button" class="th-bind-modal-trigger" data-binding-b64="{}">'
        '<span class="th-bind-modal-trigger__icon">{}</span>'
        '<span class="th-bind-modal-trigger__label">{}</span>'
        "</button>",
        payload,
        _ICON_SVG,
        label,
    )
