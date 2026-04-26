from django.core.management.base import BaseCommand

from users.models import FrontendUser
from wallets.auto_recharge import ensure_user_addresses_for_active_networks


class Command(BaseCommand):
    help = "为启用的充值网络批量派生用户专属充值地址"

    def add_arguments(self, parser):
        parser.add_argument("--user-id", type=int, default=0, help="仅处理单个前台用户 ID")

    def handle(self, *args, **options):
        user_id = int(options.get("user_id") or 0)
        qs = FrontendUser.objects.all().order_by("id")
        if user_id > 0:
            qs = qs.filter(pk=user_id)
        total = 0
        for user in qs.iterator():
            rows = ensure_user_addresses_for_active_networks(user)
            total += len(rows)
            self.stdout.write(f"user#{user.id} {user.username}: {len(rows)} address(es) ready")
        self.stdout.write(self.style.SUCCESS(f"done, processed {qs.count()} user(s), total address rows touched: {total}"))

