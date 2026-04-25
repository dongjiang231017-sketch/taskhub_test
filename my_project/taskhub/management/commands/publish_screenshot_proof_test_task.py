from decimal import Decimal

from django.core.management.base import BaseCommand

from taskhub.models import Task, TaskCategory
from taskhub.platform_publisher import get_task_platform_publisher


class Command(BaseCommand):
    help = "发布一个用于验证截图上传/后台审核流程的测试任务。"

    def add_arguments(self, parser):
        parser.add_argument("--title", default="测试任务：上传截图审核", help="测试任务标题")
        parser.add_argument("--reward-usdt", default="0.01", help="展示奖励 USDT")
        parser.add_argument("--reward-th", default="0.10", help="展示奖励 TH Coin")
        parser.add_argument("--limit", type=int, default=100, help="接取人数上限")
        parser.add_argument("--mandatory", action="store_true", help="是否显示在首页必做任务")

    def handle(self, *args, **options):
        publisher = get_task_platform_publisher()
        category, _ = TaskCategory.objects.get_or_create(
            slug="screenshot-proof",
            defaults={
                "name": "截图审核",
                "description": "需要用户上传完成截图，由后台人工审核的任务",
                "sort_order": 80,
                "is_active": True,
            },
        )
        title = options["title"]
        task, created = Task.objects.update_or_create(
            title=title,
            defaults={
                "category": category,
                "publisher": publisher,
                "description": (
                    "测试截图审核流程：请打开任意目标页面，按任务要求完成后上传截图。"
                    "\n后台可在「任务报名」中查看截图并审核通过或拒绝。"
                ),
                "budget": Decimal("0.00"),
                "reward_unit": "USDT",
                "applicants_limit": max(1, int(options["limit"])),
                "status": Task.STATUS_OPEN,
                "interaction_type": Task.INTERACTION_SCREENSHOT_PROOF,
                "binding_platform": Task.BINDING_PLATFORM_NONE,
                "interaction_config": {
                    "target_url": "https://example.com/",
                    "instructions": "完成指定页面操作后，请上传清晰截图，等待后台审核。",
                },
                "is_mandatory": bool(options["mandatory"]),
                "task_list_order": 10 if options["mandatory"] else 0,
                "reward_usdt": Decimal(str(options["reward_usdt"])),
                "reward_th_coin": Decimal(str(options["reward_th"])),
            },
        )
        verb = "已创建" if created else "已更新"
        self.stdout.write(self.style.SUCCESS(f"{verb}截图审核测试任务：ID={task.id}，标题={task.title}"))
