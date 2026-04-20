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
# 若暂时用 http://公网IP 访问管理后台，须写完整来源，例如：
# CSRF_TRUSTED_ORIGINS = ["http://8.219.124.25"]
# 并确认 Nginx 已传 X-Forwarded-Proto（HTTPS 站点一般为 https）
