from datetime import timedelta

from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import Count, Sum
from django.shortcuts import render
from django.utils import timezone

from staking.models import StakeRecord
from wallets.models import Transaction
from users.models import FrontendUser


@staff_member_required
def dashboard_view(request):
    now = timezone.localtime(timezone.now())
    today = now.date()
    days = [today - timedelta(days=i) for i in range(13, -1, -1)]
    day_labels = [day.strftime('%m-%d') for day in days]

    registrations = []
    cumulative_members = []
    total_members = FrontendUser.objects.count()
    members_by_day = {
        item['created_at__date']: item['count']
        for item in FrontendUser.objects.filter(created_at__date__gte=days[0]).values('created_at__date').annotate(count=Count('id'))
    }
    cumulative = 0
    for day in days:
        count = members_by_day.get(day, 0)
        registrations.append(count)
        cumulative += count
        cumulative_members.append(cumulative)

    total_staking_amount = StakeRecord.objects.filter(status='active').aggregate(total=Sum('amount'))['total'] or 0
    today_staking_amount = StakeRecord.objects.filter(created_at__date=today).aggregate(total=Sum('amount'))['total'] or 0
    today_release_amount = Transaction.objects.filter(change_type='reward', created_at__date=today).aggregate(total=Sum('amount'))['total'] or 0

    staking_amounts = []
    release_amounts = []
    stake_by_day = {
        item['created_at__date']: item['total']
        for item in StakeRecord.objects.filter(created_at__date__gte=days[0]).values('created_at__date').annotate(total=Sum('amount'))
    }
    release_by_day = {
        item['created_at__date']: item['total']
        for item in Transaction.objects.filter(change_type='reward', created_at__date__gte=days[0]).values('created_at__date').annotate(total=Sum('amount'))
    }
    for day in days:
        staking_amounts.append(float(stake_by_day.get(day, 0) or 0))
        release_amounts.append(float(release_by_day.get(day, 0) or 0))

    active_stake_count = StakeRecord.objects.filter(status='active').count()
    context = {
        'day_labels': day_labels,
        'registrations': registrations,
        'cumulative_members': cumulative_members,
        'total_members': total_members,
        'total_staking_amount': float(total_staking_amount),
        'today_staking_amount': float(today_staking_amount),
        'today_release_amount': float(today_release_amount),
        'staking_amounts': staking_amounts,
        'release_amounts': release_amounts,
        'daily_stake_labels': day_labels,
        'daily_release_labels': day_labels,
        'active_stake_count': active_stake_count,
    }
    return render(request, 'dashboard/dashboard.html', context)
