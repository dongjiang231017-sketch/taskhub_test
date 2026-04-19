"""
将「接口速查」写回 docs/taskhub_api.md（与 api_endpoints.py 同源）。

用法：python manage.py sync_taskhub_api_docs
"""

from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from taskhub.api_endpoints import merge_markdown_with_quickref


class Command(BaseCommand):
    help = "根据 taskhub/api_endpoints.py 更新 docs/taskhub_api.md 中的接口速查区块"

    def handle(self, *args, **options):
        path = Path(settings.BASE_DIR) / "docs" / "taskhub_api.md"
        if not path.is_file():
            self.stderr.write(self.style.ERROR(f"找不到文件: {path}"))
            return
        raw = path.read_text(encoding="utf-8")
        merged = merge_markdown_with_quickref(raw)
        path.write_text(merged, encoding="utf-8", newline="\n")
        self.stdout.write(self.style.SUCCESS(f"已更新: {path}"))
