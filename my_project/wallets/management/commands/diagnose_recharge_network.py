from django.core.management.base import BaseCommand, CommandError

from wallets.models import RechargeNetworkConfig
from wallets.recharge_diagnostics import diagnose_recharge_network


class Command(BaseCommand):
    help = "诊断自动充值网络配置是否完整、是否可派生地址、RPC 是否可连通"

    def add_arguments(self, parser):
        parser.add_argument("--chain", required=True, help="TRC20 / ERC20 / BEP20")
        parser.add_argument("--live", action="store_true", help="额外测试 RPC 实时连通性")

    def handle(self, *args, **options):
        chain = str(options["chain"] or "").strip().upper()
        live = bool(options.get("live"))
        network = RechargeNetworkConfig.objects.filter(chain=chain).first()
        if network is None:
            raise CommandError(f"未找到充值网络：{chain}")

        result = diagnose_recharge_network(network, live_check=live)
        self.stdout.write(f"network={network.display_name} chain={network.chain} active={network.is_active}")
        self.stdout.write(f"auto_ready={network.is_auto_ready} next_derivation_index={network.next_derivation_index}")
        for check in result.checks:
            status = "OK" if check.ok else "FAIL"
            self.stdout.write(f"[{status}] {check.label}: {check.detail}")
        if result.ok:
            self.stdout.write(self.style.SUCCESS("diagnostics passed"))
        else:
            self.stdout.write(self.style.WARNING("diagnostics found issues"))
