from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import Announcement, GuideCategory


class GuideApiTests(TestCase):
    def test_guide_api_uses_external_cover_when_local_cover_missing(self):
        category = GuideCategory.objects.create(
            slug="guide-api-cover-test",
            name="封面测试",
            sort_order=999,
            is_active=True,
        )
        guide = Announcement.objects.create(
            post_type=Announcement.POST_NEWBIE,
            title="TaskHub Guide",
            content="<p>Hello</p>",
            excerpt="Quick start",
            guide_category=category,
            external_cover_url="https://cdn.example.com/taskhub-cover.png",
            is_active=True,
            publish_at=timezone.now(),
        )

        list_resp = self.client.get(reverse("guides-list"))
        self.assertEqual(list_resp.status_code, 200)
        self.assertEqual(
            list_resp.json()["data"]["items"][0]["cover_url"],
            "https://cdn.example.com/taskhub-cover.png",
        )

        detail_resp = self.client.get(reverse("guides-detail", args=[guide.id]))
        self.assertEqual(detail_resp.status_code, 200)
        self.assertEqual(
            detail_resp.json()["data"]["guide"]["cover_url"],
            "https://cdn.example.com/taskhub-cover.png",
        )
