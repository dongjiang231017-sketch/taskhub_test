from unittest.mock import patch

from django.db import DatabaseError
from django.test import SimpleTestCase

from taskhub.locale_prefs import normalize_preferred_language, split_start_payload_language
from taskhub.telegram_webhook import _process_message, extract_start_payload_from_message_text
from taskhub.tiktok_apify_client import (
    _build_reposts_payload,
    _humanize_apify_tiktok_error,
    apify_tiktok_error_is_service_side,
    fetch_user_reposts_dataset_via_apify,
)


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

    def test_invalid_token_error_is_mapped_to_actionable_message(self):
        message = _humanize_apify_tiktok_error("User was not found or authentication token is not valid")

        self.assertEqual(message, "TikTok 校验服务鉴权失败，请联系管理员检查 Apify Token 配置。")

    def test_service_side_error_helper_detects_auth_failures(self):
        self.assertTrue(
            apify_tiktok_error_is_service_side("User was not found or authentication token is not valid")
        )
        self.assertFalse(apify_tiktok_error_is_service_side("并未检测到转发，请确认已完成转发后再试。"))

    @patch("taskhub.tiktok_apify_client._fetch_reposts_dataset_with_token")
    @patch("taskhub.tiktok_apify_client.get_apify_api_tokens")
    @patch("taskhub.tiktok_apify_client.apify_tiktok_configured")
    @patch("taskhub.tiktok_apify_client.get_apify_tiktok_results_per_page")
    @patch("taskhub.tiktok_apify_client.get_apify_tiktok_timeout_sec")
    @patch("taskhub.tiktok_apify_client._tiktok_actor_path_segment")
    def test_fetch_retries_fallback_token_after_auth_failure(
        self,
        mock_actor_segment,
        mock_timeout_sec,
        mock_results_per_page,
        mock_configured,
        mock_get_tokens,
        mock_fetch_with_token,
    ):
        mock_actor_segment.return_value = "clockworks~tiktok-scraper"
        mock_timeout_sec.return_value = 180
        mock_results_per_page.return_value = 60
        mock_configured.return_value = True
        mock_get_tokens.return_value = ["stale-db-token", "settings-token"]
        mock_fetch_with_token.side_effect = [
            (None, "User was not found or authentication token is not valid"),
            ([{"id": "demo-video"}], None),
        ]

        rows, err = fetch_user_reposts_dataset_via_apify("demo_user")

        self.assertIsNone(err)
        self.assertEqual(rows, [{"id": "demo-video"}])
        self.assertEqual(mock_fetch_with_token.call_count, 2)


class LocalePreferenceTests(SimpleTestCase):
    def test_normalize_preferred_language_accepts_supported_aliases(self):
        self.assertEqual(normalize_preferred_language("zh_hans"), "zh-CN")
        self.assertEqual(normalize_preferred_language("PT"), "pt-BR")
        self.assertEqual(normalize_preferred_language("es-419"), "es")

    def test_split_start_payload_language_extracts_language_and_keeps_other_tokens(self):
        language, payload = split_start_payload_language("lang_ru__ref_ABC123")

        self.assertEqual(language, "ru")
        self.assertEqual(payload, "ref_ABC123")

    def test_split_start_payload_language_handles_language_only_payload(self):
        language, payload = split_start_payload_language("lang_ar")

        self.assertEqual(language, "ar")
        self.assertIsNone(payload)


class TelegramWebhookStartTests(SimpleTestCase):
    def test_start_payload_accepts_star_typo(self):
        self.assertEqual(extract_start_payload_from_message_text("/star ref_ABC"), "ref_ABC")

    @patch("taskhub.telegram_webhook.send_welcome_message")
    @patch("users.models.FrontendUser.objects.filter")
    @patch("taskhub.telegram_webhook.TelegramStartInvitePending.objects.update_or_create")
    def test_start_still_replies_when_language_lookup_errors(self, mock_pending, mock_filter, mock_send):
        mock_pending.side_effect = DatabaseError("missing pending table")
        mock_filter.side_effect = DatabaseError("missing preferred_language column")

        _process_message(
            {
                "chat": {"type": "private"},
                "text": "/start lang_zh-CN",
                "from": {"id": 12345, "first_name": "Ada", "language_code": "zh"},
            }
        )

        mock_send.assert_called_once()
        self.assertEqual(mock_send.call_args.args[0], 12345)
        self.assertEqual(mock_send.call_args.kwargs["first_name"], "Ada")
        self.assertEqual(mock_send.call_args.kwargs["preferred_language"], "zh-CN")
