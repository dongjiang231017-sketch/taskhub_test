# Generated manually for IntegrationSecretConfig

from django.db import migrations, models


def seed_integration_secrets(apps, schema_editor):
    Model = apps.get_model("taskhub", "IntegrationSecretConfig")
    if Model.objects.exists():
        return
    from django.conf import settings

    def g(name, default=None):
        return getattr(settings, name, default)

    inst_actor = g("APIFY_INSTAGRAM_ACTOR_ID") or "apify/instagram-profile-scraper"
    if isinstance(inst_actor, str):
        inst_actor = inst_actor.strip() or "apify/instagram-profile-scraper"
    tik_actor = g("APIFY_TIKTOK_ACTOR_ID") or "clockworks/tiktok-scraper"
    if isinstance(tik_actor, str):
        tik_actor = tik_actor.strip() or "clockworks/tiktok-scraper"
    Model.objects.create(
        telegram_bot_token=g("TELEGRAM_BOT_TOKEN") or "",
        twitter_bearer_token=g("TWITTER_BEARER_TOKEN") or "",
        apify_api_token=g("APIFY_API_TOKEN") or "",
        apify_instagram_actor_id=inst_actor,
        apify_instagram_timeout_sec=int(g("APIFY_INSTAGRAM_TIMEOUT_SEC", 120) or 120),
        apify_tiktok_actor_id=tik_actor,
        apify_tiktok_timeout_sec=int(g("APIFY_TIKTOK_TIMEOUT_SEC", 180) or 180),
        apify_tiktok_results_per_page=int(g("APIFY_TIKTOK_RESULTS_PER_PAGE", 60) or 60),
    )


class Migration(migrations.Migration):

    dependencies = [
        ("taskhub", "0007_tiktok_binding_verification_mode"),
    ]

    operations = [
        migrations.CreateModel(
            name="IntegrationSecretConfig",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("telegram_bot_token", models.TextField(blank=True, db_comment="Mini App 登录与入群校验 getChatMember；与 BotFather 一致", default="", verbose_name="Telegram Bot Token")),
                ("twitter_bearer_token", models.TextField(blank=True, db_comment="API v2 只读 Bearer，用于转发/关注校验", default="", verbose_name="Twitter / X Bearer Token")),
                ("apify_api_token", models.TextField(blank=True, db_comment="Instagram / TikTok 等 Actor 调用", default="", verbose_name="Apify API Token")),
                ("apify_instagram_actor_id", models.CharField(blank=True, db_comment="默认 apify/instagram-profile-scraper；留空用 settings", default="", max_length=256, verbose_name="Apify Instagram Actor ID")),
                ("apify_instagram_timeout_sec", models.PositiveIntegerField(blank=True, db_comment="留空则使用 settings / 环境变量", null=True, verbose_name="Instagram 请求超时（秒）")),
                ("apify_tiktok_actor_id", models.CharField(blank=True, db_comment="默认 clockworks/tiktok-scraper", default="", max_length=256, verbose_name="Apify TikTok Actor ID")),
                ("apify_tiktok_timeout_sec", models.PositiveIntegerField(blank=True, db_comment="留空则使用 settings / 环境变量", null=True, verbose_name="TikTok 请求超时（秒）")),
                ("apify_tiktok_results_per_page", models.PositiveIntegerField(blank=True, db_comment="留空则使用 settings / 环境变量", null=True, verbose_name="TikTok Reposts 每页条数")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="更新时间")),
            ],
            options={
                "verbose_name": "第三方集成密钥",
                "verbose_name_plural": "第三方集成密钥",
                "db_table": "task_integration_secret_config",
            },
        ),
        migrations.RunPython(seed_integration_secrets, migrations.RunPython.noop),
    ]
