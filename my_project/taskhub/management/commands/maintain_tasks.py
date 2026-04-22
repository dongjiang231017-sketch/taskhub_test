"""建议由 cron 每 1～5 分钟执行：python manage.py maintain_tasks"""

from django.core.management.base import BaseCommand

from taskhub.task_lifecycle import (
    close_tasks_past_deadline,
    expire_stale_pending_applications,
    release_stale_takers_when_completed_deadline_passed,
)


class Command(BaseCommand):
    help = "取消超时未完成的待处理报名；将已过截止时间的可报名任务标为已完成；释放未完成报名以便任务再开放。"

    def handle(self, *args, **options):
        expired = expire_stale_pending_applications()
        closed = close_tasks_past_deadline()
        released_extra = release_stale_takers_when_completed_deadline_passed()
        self.stdout.write(
            self.style.SUCCESS(
                f"超时取消报名 {expired} 条；到期关闭任务 {closed} 条；"
                f"已为到期 completed 任务补释放报名 {released_extra} 条。"
            )
        )
