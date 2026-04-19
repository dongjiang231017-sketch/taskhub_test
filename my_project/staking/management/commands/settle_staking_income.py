from django.core.management.base import BaseCommand
from django.utils import timezone
from staking.models import StakeRecord


class Command(BaseCommand):
    help = '结算所有开启中的质押收益'

    def handle(self, *args, **options):
        now = timezone.now()
        settled = 0
        for stake in StakeRecord.objects.filter(status='active'):
            income = stake.settle_daily()
            if income:
                settled += 1
                self.stdout.write(self.style.SUCCESS(f'已结算 {stake.user.username} 的质押收益：{income}'))
        self.stdout.write(self.style.SUCCESS(f'共结算 {settled} 个质押账户'))
