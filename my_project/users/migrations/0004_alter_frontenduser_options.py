from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0003_telegram_checkin_miniapp"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="frontenduser",
            options={
                "verbose_name": "会员",
                "verbose_name_plural": "会员列表",
            },
        ),
    ]
