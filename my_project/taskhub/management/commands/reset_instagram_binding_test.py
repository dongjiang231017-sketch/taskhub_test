"""联调：将 Instagram 绑定报名恢复为 pending，便于再次调用 verify-instagram。"""

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from taskhub.models import Task, TaskApplication


class Command(BaseCommand):
    help = (
        "将指定 TaskApplication 恢复为待处理（pending），用于 Instagram 绑定校验重复测试。"
        "仅允许 interaction_type=account_binding 且 binding_platform=instagram 的报名。"
    )

    def add_arguments(self, parser):
        parser.add_argument("application_id", type=int, help="TaskApplication 主键 id")
        parser.add_argument(
            "--clear-reward-paid",
            action="store_true",
            help="同时清空 reward_paid_at（下次校验可能再次触发发奖逻辑，仅测试慎用）",
        )
        parser.add_argument("--dry-run", action="store_true", help="只打印不写库")

    def handle(self, *args, **options):
        aid = options["application_id"]
        dry = options["dry_run"]

        app = TaskApplication.objects.select_related("task").filter(pk=aid).first()
        if not app:
            raise CommandError(f"报名不存在: application_id={aid}")
        task = app.task
        if task.interaction_type != Task.INTERACTION_ACCOUNT_BINDING:
            raise CommandError("该任务不是「账号绑定」类型，本命令拒绝执行")
        if task.binding_platform != Task.BINDING_INSTAGRAM:
            raise CommandError("该任务不是 Instagram 绑定，本命令拒绝执行（避免误改其它平台报名）")

        self.stdout.write(
            f"application_id={app.id} task_id={task.id} applicant_id={app.applicant_id} "
            f"当前 status={app.status!r} reward_paid_at={app.reward_paid_at}"
        )

        if dry:
            self.stdout.write(self.style.WARNING("--dry-run，未写入数据库"))
            return

        with transaction.atomic():
            app = TaskApplication.objects.select_for_update().get(pk=aid)
            task = Task.objects.select_for_update().get(pk=app.task_id)

            app.status = TaskApplication.STATUS_PENDING
            app.self_verified_at = None
            app.decided_at = None
            fields = ["status", "self_verified_at", "decided_at", "updated_at"]
            if options["clear_reward_paid"]:
                app.reward_paid_at = None
                fields.append("reward_paid_at")
            app.save(update_fields=fields)

            # 普通任务曾因单名额录用被标为 completed 时，若无其它已录用则恢复为 open
            if task.status == Task.STATUS_COMPLETED:
                has_other_accepted = TaskApplication.objects.filter(
                    task=task, status=TaskApplication.STATUS_ACCEPTED
                ).exclude(pk=app.pk).exists()
                if not has_other_accepted:
                    task.status = Task.STATUS_OPEN
                    task.save(update_fields=["status", "updated_at"])
                    self.stdout.write(self.style.WARNING(f"任务 task_id={task.id} 已恢复为 open"))

        self.stdout.write(
            self.style.SUCCESS(
                f"已恢复为 pending，可再次 POST /api/v1/me/applications/{aid}/verify-instagram/"
            )
        )
