"""
将 Telegram Bot 的 Webhook 指到本项目的 /api/v1/telegram/webhook/。

用法示例：
  export TELEGRAM_WEBHOOK_SECRET="$(openssl rand -hex 24)"
  python manage.py telegram_set_webhook --url https://你的域名/api/v1/telegram/webhook/

secret 须与服务器环境变量 TELEGRAM_WEBHOOK_SECRET 一致（并在 setWebhook 时传给 Telegram）。
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from taskhub.integration_config import get_telegram_bot_token


class Command(BaseCommand):
    help = "调用 Telegram setWebhook（需已配置 TELEGRAM_BOT_TOKEN）"

    def add_arguments(self, parser):
        parser.add_argument(
            "--url",
            required=True,
            help="完整 HTTPS URL，例如 https://example.com/api/v1/telegram/webhook/",
        )
        parser.add_argument(
            "--secret",
            default="",
            help="Webhook secret_token；省略则用 settings.TELEGRAM_WEBHOOK_SECRET（可为空但不推荐生产）",
        )

    def handle(self, *args, **options):
        token = get_telegram_bot_token()
        if not token:
            raise CommandError("未配置 TELEGRAM_BOT_TOKEN，无法 setWebhook")

        url = str(options["url"]).strip()
        if not url.lower().startswith("https://"):
            raise CommandError("Webhook URL 必须为 https://")

        secret = (options.get("secret") or "").strip() or (getattr(settings, "TELEGRAM_WEBHOOK_SECRET", None) or "").strip()

        api = f"https://api.telegram.org/bot{token}/setWebhook"
        form: dict[str, str] = {"url": url}
        if secret:
            form["secret_token"] = secret
        data = urllib.parse.urlencode(form).encode("utf-8")
        req = urllib.request.Request(api, data=data, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            raise CommandError(f"Telegram API HTTP 错误: {e.code} {e.read().decode('utf-8', errors='replace')}") from e
        except urllib.error.URLError as e:
            raise CommandError(f"网络错误: {e}") from e

        try:
            j = json.loads(raw)
        except json.JSONDecodeError as e:
            raise CommandError(f"无效响应: {raw[:500]}") from e

        if not j.get("ok"):
            raise CommandError(f"setWebhook 失败: {j}")

        self.stdout.write(self.style.SUCCESS(json.dumps(j, ensure_ascii=False, indent=2)))
        if secret:
            self.stdout.write(self.style.WARNING("请确认服务器已设置 TELEGRAM_WEBHOOK_SECRET 且与此处 secret_token 一致。"))
        else:
            self.stdout.write(
                self.style.WARNING("未使用 secret_token：建议设置 TELEGRAM_WEBHOOK_SECRET 后带 --secret 重新执行。")
            )
