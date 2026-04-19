"""建议由 cron 每 1～5 分钟执行：python manage.py maintain_tasks"""

from django.core.management.base import BaseCommand

from taskhub.task_lifecycle import close_tasks_past_deadline, expire_stale_pending_applications


class Command(BaseCommand):
    help = "取消超时未完成的待处理报名；将已过截止时间的可报名任务标为已完成。"

    def handle(self, *args, **options):
        expired = expire_stale_pending_applications()
        closed = close_tasks_past_deadline()
        self.stdout.write(
            self.style.SUCCESS(
                f"超时取消报名 {expired} 条；到期关闭任务 {closed} 条。"
            )
        )
