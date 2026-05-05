"""建议由 cron 每 1～5 分钟执行：python manage.py maintain_platform_stats"""

from django.core.management.base import BaseCommand

from taskhub.task_lifecycle import advance_virtual_platform_stats


class Command(BaseCommand):
    help = "按整小时结算首页统计虚拟参数的随机增长。"

    def handle(self, *args, **options):
        summary = advance_virtual_platform_stats()
        self.stdout.write(
            self.style.SUCCESS(
                "首页排行榜统计虚拟增长："
                f"更新={summary['updated']}，"
                f"跨越小时数={summary['elapsed_hours']}，"
                f"任务总数+{summary['added_total_tasks']}，"
                f"总发放奖励+{summary['added_total_rewards_usdt']} USDT，"
                f"总用户数+{summary['added_total_users']}，"
                f"运营天数+{summary['added_operating_days']}。"
            )
        )
