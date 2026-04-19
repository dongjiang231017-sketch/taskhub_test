"""清空指定前台用户的全部任务报名（用于测试账号重测）。"""

from django.core.management.base import BaseCommand, CommandError

from users.models import FrontendUser

from taskhub.models import TaskApplication


class Command(BaseCommand):
    help = "删除指定用户的所有 TaskApplication 记录（任务报名/完成记录同表清空）"

    def add_arguments(self, parser):
        parser.add_argument("--user-id", type=int, help="FrontendUser 主键")
        parser.add_argument("--username", type=str, help="FrontendUser.username")

    def handle(self, *args, **options):
        uid = options.get("user_id")
        username = (options.get("username") or "").strip()
        if not uid and not username:
            raise CommandError("请指定 --user-id 或 --username")
        if uid:
            user = FrontendUser.objects.filter(pk=uid).first()
        else:
            user = FrontendUser.objects.filter(username=username).first()
        if not user:
            raise CommandError("用户不存在")
        qs = TaskApplication.objects.filter(applicant=user)
        n = qs.count()
        qs.delete()
        self.stdout.write(self.style.SUCCESS(f"已删除用户 {user.id} ({user.username}) 的 {n} 条任务报名记录"))
