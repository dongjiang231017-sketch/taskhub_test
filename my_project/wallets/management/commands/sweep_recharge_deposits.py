from django.core.management.base import BaseCommand

from wallets.auto_recharge import sweep_network_recharges
from wallets.models import RechargeNetworkConfig


class Command(BaseCommand):
    help = "把用户充值地址中的 USDT 自动归集到配置的总地址"

    def add_arguments(self, parser):
        parser.add_argument("--chain", default="", help="仅处理单条链：TRC20 / ERC20 / BEP20")

    def handle(self, *args, **options):
        chain = str(options.get("chain") or "").strip().upper()
        qs = RechargeNetworkConfig.objects.filter(is_active=True, sweep_enabled=True).order_by("sort_order", "id")
        if chain:
            qs = qs.filter(chain=chain)
        for network in qs:
            stats = sweep_network_recharges(network)
            self.stdout.write(
                f"{network.chain}: queued={stats['queued']} completed={stats['completed']} topped_up={stats['topped_up']}"
            )
        self.stdout.write(self.style.SUCCESS("sweep complete"))
