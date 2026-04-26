from __future__ import annotations

from django.db import migrations
from django.utils import timezone


CONTENT_HTML = """
<h2>关于任务邀请好友拉新活动会员等级</h2>
<p>邀请好友加入 TaskHub，会员等级、充值分佣、任务分成和团队长扶持政策均可在后台配置，前台展示以后台当前配置为准。</p>
<h3>一、会员等级</h3>
<ul>
  <li><strong>VIP0：</strong>加入费用 0 USDT；只能领取免费任务；提现手续费 20%。</li>
  <li><strong>VIP1：</strong>费用 50 USDT；可以领取官方发布任务；一天领取数量 1 笔；提现手续费 10%。</li>
  <li><strong>VIP2：</strong>费用 100 USDT；可以领取官方发布任务；一天领取数量 2 笔；可领取佣金更高的任务；提现手续费 5%。</li>
  <li><strong>VIP3：</strong>费用 1000 USDT；不限制任务，只要平台任务都可以做；提现手续费 0%。</li>
</ul>
<h3>二、动态收益：二级分佣模型</h3>
<ul>
  <li><strong>一级佣金：</strong>A 邀请 B 充值，A 可获得 B 充值金额的 10%。</li>
  <li><strong>二级佣金：</strong>B 邀请 C 充值，A 可获得 C 充值金额的 5%。</li>
  <li><strong>任务分成：</strong>下级每完成一笔任务，上级可获得任务佣金的 20%（一级）和 10%（二级）额外奖励。</li>
</ul>
<h3>三、团队长（超级代理）扶持政策</h3>
<table>
  <thead>
    <tr><th>等级名称</th><th>准入门槛</th><th>团队总充值业绩目标</th><th>额外团队业绩提成</th></tr>
  </thead>
  <tbody>
    <tr><td>初级代理</td><td>直推 10 个 VIP</td><td>累计 2,000 USDT</td><td>2%</td></tr>
    <tr><td>中级合伙人</td><td>直推 30 个 VIP</td><td>每月 10,000 USDT</td><td>5%</td></tr>
    <tr><td>顶级领袖</td><td>直推 100 个 VIP</td><td>每月 50,000 USDT</td><td>10%</td></tr>
  </tbody>
</table>
""".strip()


def forwards(apps, schema_editor):
    GuideCategory = apps.get_model("announcements", "GuideCategory")
    Announcement = apps.get_model("announcements", "Announcement")

    category, _ = GuideCategory.objects.update_or_create(
        slug="invite-activity",
        defaults={
            "name": "邀请活动",
            "sort_order": 35,
            "is_active": True,
        },
    )
    Announcement.objects.update_or_create(
        slug="invite-friends-growth-activity",
        defaults={
            "post_type": "newbie_guide",
            "title": "关于任务邀请好友拉新活动会员等级",
            "content": CONTENT_HTML,
            "excerpt": "会员等级、充值二级分佣、任务分成与团队长扶持政策说明。",
            "guide_type": "article",
            "external_cover_url": "",
            "video_url": "",
            "duration_display": "",
            "read_minutes": 4,
            "is_featured": False,
            "guide_category": category,
            "category_key": "",
            "category_label": "",
            "author_name": "TaskHub 官方教程",
            "is_active": True,
            "publish_at": timezone.now(),
            "expire_at": None,
        },
    )


class Migration(migrations.Migration):
    dependencies = [
        ("announcements", "0006_announcement_external_cover_url_and_refresh_guides"),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
