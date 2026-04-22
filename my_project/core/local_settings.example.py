"""
服务器专用配置（不依赖 .env / 环境变量）。

部署步骤：
1. 复制本文件为同目录下的 local_settings.py（文件名必须完全一致）
2. 填写下面的 DATABASES（宝塔「数据库」里该库的账号）
3. 按需取消注释 SECRET_KEY / DEBUG / ALLOWED_HOSTS 等

注意：local_settings.py 已加入 .gitignore，勿提交到 Git。
本文件内不要 import django.conf.settings，避免循环引用。
"""

# 必填：覆盖默认 MySQL 连接（宝塔专用库用户，不要用 root）
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.mysql",
        "NAME": "在这里填写数据库名",
        "USER": "在这里填写用户名",
        "PASSWORD": "在这里填写密码",
        "HOST": "127.0.0.1",
        "PORT": "3306",
        "OPTIONS": {
            "init_command": "SET sql_mode='STRICT_TRANS_TABLES'",
        },
    }
}

# 可选：生产环境建议一并配置（不配则仍用 settings.py 里默认值 + .env）
# SECRET_KEY = "用 django.core.management.utils.get_random_secret_key 生成"
# DEBUG = False
# ALLOWED_HOSTS = ["你的域名", "127.0.0.1"]
# CSRF_TRUSTED_ORIGINS = ["https://你的域名"]

# 若改完仍报 DisallowedHost：1）改完务必重启 Gunicorn；2）在服务器执行
#   python manage.py shell -c "from django.conf import settings; print(settings.ALLOWED_HOSTS)"
#   确认列表里真有你的域名；3）若仍不行，可在环境变量设 ALLOWED_HOSTS_EXTRA=i.tongrentang.info（逗号分隔多个）
# 4）HTTPS 反代若配置了 X-Forwarded-Host，须与 ALLOWED_HOSTS 一致；可临时在下方取消注释以排查：
# USE_X_FORWARDED_HOST = False
# 若暂时用 http://公网IP 访问管理后台，须写完整来源，例如：
# CSRF_TRUSTED_ORIGINS = ["http://8.219.124.25"]
# 并确认 Nginx 已传 X-Forwarded-Proto（HTTPS 站点一般为 https）

# Telegram Bot Webhook（先点 t.me/bot?start=ref_… 再打开 Mini App 时补绑推荐人；见 docs/taskhub_api.md §2.5）
# TELEGRAM_WEBHOOK_SECRET=与 python manage.py telegram_set_webhook 传入的 secret_token 一致
# TELEGRAM_START_INVITE_PENDING_TTL_SECONDS=604800

# 排行 / 邀请（可选，不配则用 settings.py 默认值）
# Foxi 式邀请链接：生产务必配置 Bot 用户名（无 @），否则 invite_link.full_url 仍是浏览器打开的 https://你的域名/invite/...
# TELEGRAM_BOT_USERNAME=YourBot
# TELEGRAM_INVITE_START_PREFIX=ref_
# 与上同时配时，邀请链接 full_url 为 https://t.me/jiangcaiji_bot/task_hub_test?startapp=ref_…（按你 BotFather 实际短名改）
# TELEGRAM_MINI_APP_SHORT_NAME=task_hub_test
# Telegram 机器人欢迎 / 私聊推送（可选）
# TELEGRAM_MINI_APP_URL=https://你的前端域名
# TELEGRAM_COMMUNITY_URL=https://t.me/你的社群
# TELEGRAM_ANNOUNCEMENT_URL=https://t.me/你的公告频道
# TELEGRAM_BOT_WELCOME_IMAGE_URL=https://你的域名/path/welcome.jpg
# TELEGRAM_BOT_WELCOME_TEXT=🎉 欢迎加入 TaskHub\n\n你好，{name}！
# 未配 TELEGRAM_BOT_USERNAME 时可用站内或自定义前缀落地页：
# INVITE_LINK_BASE_URL=https://task.example.com
# INVITE_COMMISSION_RATE=0.10
# PLATFORM_STATS_ANCHOR_DATE=2026-01-01
