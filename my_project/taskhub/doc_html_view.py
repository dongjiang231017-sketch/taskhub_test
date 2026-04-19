"""
将 docs/taskhub_api.md 渲染为独立 HTML 页面，便于分享给前端。
"""

from __future__ import annotations

import markdown
from django.conf import settings
from django.http import Http404, HttpResponse, JsonResponse
from django.views.decorators.http import require_GET

from taskhub.api_endpoints import API_PREFIX, get_endpoints_for_public_json, merge_markdown_with_quickref


def _doc_path():
    return settings.BASE_DIR / "docs" / "taskhub_api.md"


def _page_html(title: str, toc_html: str, body_html: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{title}</title>
  <style>
    :root {{
      --bg: #f6f8fa;
      --card: #ffffff;
      --text: #1f2328;
      --muted: #59636e;
      --border: #d1d9e0;
      --code-bg: #f0f3f6;
      --accent: #0969da;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto,
        "PingFang SC", "Microsoft YaHei", sans-serif;
      background: var(--bg);
      color: var(--text);
      line-height: 1.6;
    }}
    .wrap {{
      max-width: 920px;
      margin: 0 auto;
      padding: 24px 20px 48px;
    }}
    header {{
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 20px 24px;
      margin-bottom: 20px;
    }}
    header h1 {{
      margin: 0 0 8px;
      font-size: 1.5rem;
      font-weight: 600;
    }}
    header p {{
      margin: 0;
      color: var(--muted);
      font-size: 0.9rem;
    }}
    header a {{
      color: var(--accent);
      text-decoration: none;
    }}
    header a:hover {{ text-decoration: underline; }}
    .layout {{
      display: grid;
      grid-template-columns: minmax(0, 1fr);
      gap: 20px;
    }}
    @media (min-width: 960px) {{
      .layout {{
        grid-template-columns: 220px minmax(0, 1fr);
        align-items: start;
      }}
    }}
    nav.toc {{
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 16px 18px;
      font-size: 0.85rem;
      position: sticky;
      top: 16px;
    }}
    nav.toc .toc-title {{
      font-weight: 600;
      margin-bottom: 10px;
      color: var(--muted);
      font-size: 0.75rem;
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }}
    nav.toc ul {{
      list-style: none;
      margin: 0;
      padding: 0;
    }}
    nav.toc ul ul {{ margin-left: 12px; }}
    nav.toc li {{ margin: 4px 0; }}
    nav.toc a {{
      color: var(--text);
      text-decoration: none;
    }}
    nav.toc a:hover {{ color: var(--accent); }}
    main {{
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 28px 32px 36px;
    }}
    main h1, main h2, main h3, main h4 {{
      scroll-margin-top: 16px;
    }}
    main h1 {{ font-size: 1.35rem; border-bottom: 1px solid var(--border); padding-bottom: 0.35em; }}
    main h2 {{ font-size: 1.15rem; margin-top: 1.6em; }}
    main h3 {{ font-size: 1.05rem; margin-top: 1.2em; }}
    main code {{
      background: var(--code-bg);
      padding: 0.15em 0.4em;
      border-radius: 4px;
      font-size: 0.9em;
    }}
    main pre {{
      background: #1c2128;
      color: #e6edf3;
      padding: 16px 18px;
      border-radius: 8px;
      overflow-x: auto;
      font-size: 0.85rem;
      line-height: 1.45;
    }}
    main pre code {{
      background: transparent;
      padding: 0;
      color: inherit;
    }}
    main ul {{ padding-left: 1.2em; }}
    main a {{ color: var(--accent); }}
    main hr {{ border: none; border-top: 1px solid var(--border); margin: 2em 0; }}
    footer {{
      margin-top: 24px;
      text-align: center;
      font-size: 0.8rem;
      color: var(--muted);
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <header>
      <h1>{title}</h1>
      <p>与 <code>docs/taskhub_api.md</code> 同源；机器可读目录：
        <a href="/api/v1/docs/">/api/v1/docs/</a>
        · 健康检查 <a href="/api/v1/health/">/api/v1/health/</a></p>
    </header>
    <div class="layout">
      <nav class="toc" aria-label="目录">
        <div class="toc-title">目录</div>
        {toc_html}
      </nav>
      <main class="markdown-body">
        {body_html}
      </main>
    </div>
    <footer>TaskHub API · 由后端自动生成</footer>
  </div>
</body>
</html>"""


@require_GET
def taskhub_api_docs_html(request):
    path = _doc_path()
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise Http404("未找到 docs/taskhub_api.md") from exc

    md = markdown.Markdown(
        extensions=[
            "markdown.extensions.fenced_code",
            "markdown.extensions.tables",
            "markdown.extensions.toc",
            "markdown.extensions.sane_lists",
        ],
        extension_configs={
            "toc": {
                "title": "",
                "toc_depth": 3,
                "anchorlink": True,
            },
        },
    )
    merged = merge_markdown_with_quickref(raw)
    body_html = md.convert(merged)
    toc_html = (md.toc or "").strip()
    if not toc_html:
        toc_html = '<p style="color:var(--muted);margin:0;font-size:0.9rem">（本页无目录）</p>'
    html = _page_html("TaskHub API 文档", toc_html, body_html)
    return HttpResponse(html, content_type="text/html; charset=utf-8")


@require_GET
def openapi_discovery_json(request):
    """
    部分脚手架会请求根路径 `/openapi.json`。
    本响应为「接口发现」用 JSON（含与 `GET /api/v1/docs/` 同源的 endpoints），非完整 OpenAPI paths 定义。
    """
    return JsonResponse(
        {
            "openapi": "3.0.3",
            "info": {
                "title": "TaskHub API",
                "version": "1.0.0",
                "description": "发现用摘要；完整说明见 /docs/taskhub-api/ 与 docs/taskhub_api.md",
            },
            "servers": [
                {"url": f"{request.scheme}://{request.get_host()}{API_PREFIX.rstrip('/')}"},
            ],
            "endpoints": get_endpoints_for_public_json(),
        },
        json_dumps_params={"ensure_ascii": False},
    )
