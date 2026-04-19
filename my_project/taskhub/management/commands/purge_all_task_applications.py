"""清空全部任务报名（联调/重置用）；慎用生产环境。"""

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from taskhub.models import Task, TaskApplication


class Command(BaseCommand):
    help = "删除数据库中全部 TaskApplication，并按需将受影响任务恢复为 open（无已录用、无报名时的 completed 等）。"

    def add_arguments(self, parser):
        parser.add_argument(
            "--yes",
            action="store_true",
            help="必须传入本参数才会真正删除，防止误操作",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="只统计条数，不写库",
        )

    def handle(self, *args, **options):
        n = TaskApplication.objects.count()
        self.stdout.write(f"当前 TaskApplication 条数: {n}")
        if n == 0:
            self.stdout.write("无需清空。")
            return

        if options["dry_run"]:
            self.stdout.write(self.style.WARNING("--dry-run，未删除"))
            return

        if not options["yes"]:
            raise CommandError("拒绝执行：请附加 --yes 确认要删除全部报名记录")

        task_ids = list(TaskApplication.objects.values_list("task_id", flat=True).distinct())

        with transaction.atomic():
            TaskApplication.objects.all().delete()

            for tid in task_ids:
                t = Task.objects.filter(pk=tid).first()
                if not t:
                    continue
                has_accepted = t.applications.filter(status=TaskApplication.STATUS_ACCEPTED).exists()
                has_any = t.applications.exists()
                if t.status == Task.STATUS_IN_PROGRESS and not has_accepted:
                    t.status = Task.STATUS_OPEN
                    t.save(update_fields=["status", "updated_at"])
                    self.stdout.write(f"任务 task_id={tid} → open（进行中但已无报名）")
                elif t.status == Task.STATUS_COMPLETED and not has_any:
                    t.status = Task.STATUS_OPEN
                    t.save(update_fields=["status", "updated_at"])
                    self.stdout.write(f"任务 task_id={tid} → open（已无报名）")

        self.stdout.write(self.style.SUCCESS(f"已删除全部 {n} 条报名记录。"))
