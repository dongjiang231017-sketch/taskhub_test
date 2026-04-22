from django.test import SimpleTestCase

from taskhub.tiktok_apify_client import _build_reposts_payload, _humanize_apify_tiktok_error


class TikTokApifyClientTests(SimpleTestCase):
    def test_reposts_payload_does_not_send_video_only_sorting_field(self):
        payload = _build_reposts_payload("demo_user", 60)

        self.assertEqual(payload["profiles"], ["demo_user"])
        self.assertEqual(payload["profileScrapeSections"], ["reposts"])
        self.assertEqual(payload["resultsPerPage"], 60)
        self.assertNotIn("profileSorting", payload)

    def test_validation_error_is_mapped_to_configuration_message(self):
        message = _humanize_apify_tiktok_error("Actor input schema validation failed: profileSorting")

        self.assertEqual(message, "TikTok 校验服务参数配置有误，请联系管理员处理。")

