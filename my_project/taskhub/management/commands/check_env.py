"""
检查 .env 与数据库配置是否被 Django 读到（不打印密码）。

用法：python manage.py check_env
"""

import os

from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "检查 .env 路径、MYSQL_* 与 Django DATABASES 配置（不输出密码）"

    def handle(self, *args, **options):
        env_path = settings.BASE_DIR / ".env"
        ls_path = settings.BASE_DIR / "core" / "local_settings.py"
        self.stdout.write(f".env 路径: {env_path}")
        self.stdout.write(f".env 存在: {env_path.is_file()}")
        self.stdout.write(f"core/local_settings.py 路径: {ls_path}")
        self.stdout.write(f"core/local_settings.py 存在: {ls_path.is_file()}")
        try:
            import dotenv  # noqa: F401

            self.stdout.write("python-dotenv: 已安装")
        except ImportError:
            self.stderr.write(self.style.ERROR("python-dotenv: 未安装，请 pip install -r requirements.txt"))

        for key in ("MYSQL_DATABASE", "MYSQL_USER", "MYSQL_PASSWORD", "MYSQL_HOST", "MYSQL_PORT"):
            raw = os.environ.get(key)
            if raw is None:
                self.stdout.write(f"os.environ[{key}]: (未设置)")
            elif key == "MYSQL_PASSWORD":
                self.stdout.write(f"os.environ[{key}]: 已设置，长度 {len(raw)}")
            else:
                self.stdout.write(f"os.environ[{key}]: {raw!r}")

        db = settings.DATABASES["default"]
        self.stdout.write("--- Django DATABASES['default'] ---")
        self.stdout.write(f"USER={db['USER']!r} NAME={db['NAME']!r} HOST={db['HOST']!r} PORT={db['PORT']!r}")
        pw = db.get("PASSWORD") or ""
        self.stdout.write(f"PASSWORD: {'空' if not str(pw).strip() else f'非空，长度 {len(str(pw))}'}")

        if str(db["USER"]).lower() == "root":
            self.stdout.write(
                self.style.WARNING(
                    "当前仍为 MySQL 用户 root。请在 .env 中设置 MYSQL_USER / MYSQL_PASSWORD（宝塔专用数据库用户），"
                    "并确认 .env 与 manage.py 在同一目录。"
                )
            )
