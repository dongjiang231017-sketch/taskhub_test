from django.core.management.base import BaseCommand

from wallets.auto_recharge import sync_network_recharges
from wallets.models import RechargeNetworkConfig


class Command(BaseCommand):
    help = "扫描链上 USDT 充值并按确认数自动入账"

    def add_arguments(self, parser):
        parser.add_argument("--chain", default="", help="仅同步单条链：TRC20 / ERC20 / BEP20")

    def handle(self, *args, **options):
        chain = str(options.get("chain") or "").strip().upper()
        qs = RechargeNetworkConfig.objects.filter(is_active=True).order_by("sort_order", "id")
        if chain:
            qs = qs.filter(chain=chain)
        for network in qs:
            stats = sync_network_recharges(network)
            self.stdout.write(
                f"{network.chain}: detected={stats['detected']} credited={stats['credited']} pending={stats['pending']}"
            )
        self.stdout.write(self.style.SUCCESS("sync complete"))

