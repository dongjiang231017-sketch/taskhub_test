# Generated manually: add admin-only proxy for screenshot proof review.

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("taskhub", "0024_alter_platformstatsdisplayconfig_options_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="ScreenshotProofReview",
            fields=[],
            options={
                "verbose_name": "截图任务审核",
                "verbose_name_plural": "截图任务审核",
                "proxy": True,
                "indexes": [],
                "constraints": [],
            },
            bases=("taskhub.taskapplication",),
        ),
    ]
