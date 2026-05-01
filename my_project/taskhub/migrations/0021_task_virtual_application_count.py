from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("taskhub", "0020_integrationsecretconfig_apify_twitter_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="task",
            name="virtual_application_count",
            field=models.PositiveIntegerField(
                db_comment="仅用于前台任务列表展示的虚拟参与人数，会叠加真实报名数",
                default=0,
                verbose_name="虚拟参与人数",
            ),
        ),
    ]
