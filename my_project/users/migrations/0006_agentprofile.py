from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("users", "0005_frontenduser_preferred_language"),
    ]

    operations = [
        migrations.CreateModel(
            name="AgentProfile",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "include_self",
                    models.BooleanField(
                        db_comment="开启后代理后台可见根节点本人及所有下级；关闭后仅可见下级。",
                        default=True,
                        verbose_name="包含代理本人",
                    ),
                ),
                ("is_active", models.BooleanField(default=True, verbose_name="是否启用")),
                ("remark", models.CharField(blank=True, default="", max_length=255, verbose_name="备注")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="创建时间")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="更新时间")),
                (
                    "backend_user",
                    models.OneToOneField(
                        db_comment="用于登录 /agent-admin/ 的 Django 后台账号；保存后会自动开启 staff。",
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="agent_profile",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="后台登录账号",
                    ),
                ),
                (
                    "root_user",
                    models.OneToOneField(
                        db_comment="该前台用户作为代理伞下数据根节点。",
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="agent_profile",
                        to="users.frontenduser",
                        verbose_name="代理前台账号",
                    ),
                ),
            ],
            options={
                "verbose_name": "代理后台账号",
                "verbose_name_plural": "代理后台账号",
                "db_table": "frontend_agent_profile",
            },
        ),
    ]
