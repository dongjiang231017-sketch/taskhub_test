# Generated manually: TikTok 绑定改为「用户自校验 + verify-tiktok」，与旧 profile_link_proof 区分

from django.db import migrations


def forwards(apps, schema_editor):
    Task = apps.get_model("taskhub", "Task")
    Task.objects.filter(
        interaction_type="account_binding",
        binding_platform="tiktok",
        verification_mode="profile_link_proof",
    ).update(verification_mode="user_self_confirm")


class Migration(migrations.Migration):
    dependencies = [
        ("taskhub", "0006_task_reward_and_reward_paid_at"),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
