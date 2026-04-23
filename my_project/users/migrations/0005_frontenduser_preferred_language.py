from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0004_alter_frontenduser_options"),
    ]

    operations = [
        migrations.AddField(
            model_name="frontenduser",
            name="preferred_language",
            field=models.CharField(
                choices=[
                    ("zh-CN", "中文"),
                    ("en", "English"),
                    ("ru", "Русский"),
                    ("ar", "العربية"),
                    ("fr", "Français"),
                    ("pt-BR", "Português"),
                    ("es", "Español"),
                    ("vi", "Tiếng Việt"),
                ],
                db_comment="机器人入口 / Mini App 首选语言",
                default="en",
                max_length=16,
                verbose_name="界面语言",
            ),
        ),
    ]
