from django.apps import AppConfig


class TaskhubConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "taskhub"
    verbose_name = "任务平台"

    def ready(self):
        """隐藏与 TaskHub 无关的旧业务后台入口（模型仍保留，仅不在 Admin 中展示）。"""
        from . import signals  # noqa: F401 — 注册 Task post_save 等信号

        from django.contrib import admin
        from django.contrib.admin.exceptions import NotRegistered

        try:
            from staking.models import StakeRecord, StakingProduct

            admin.site.unregister(StakeRecord)
            admin.site.unregister(StakingProduct)
        except (ImportError, NotRegistered):
            pass

