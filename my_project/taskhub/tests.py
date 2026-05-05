from unittest.mock import MagicMock, patch

from datetime import timedelta
from decimal import Decimal

from django.test import TestCase, override_settings
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.utils import timezone

from users.agent_scope import AGENT_ROOT_USER_SESSION_KEY
from users.models import AgentProfile, FrontendUser
from wallets.auto_recharge import (
    DetectedTransfer,
    EvmUsdtClient,
    _EVM_TRANSFER_TOPIC,
    _tron_base58_from_private_key,
    ensure_user_recharge_address,
    sync_network_recharges,
)
from wallets.models import RechargeNetworkConfig, RechargeRequest, Transaction, UserRechargeAddress, Wallet

from django.db import DatabaseError
from django.test import SimpleTestCase

from taskhub.models import (
    ApiToken,
    MembershipLevelConfig,
    PlatformStatsDisplayConfig,
    ReferralRewardConfig,
    Task,
    TaskApplication,
)
from taskhub.api_views import _twitter_verify_error, enrich_task_card_fields, serialize_task
from taskhub.locale_prefs import normalize_preferred_language, split_start_payload_language
from taskhub.task_lifecycle import advance_virtual_application_counts, advance_virtual_platform_stats
from taskhub.task_rewards import grant_task_completion_reward
from taskhub.telegram_group_client import extract_telegram_chat_id_from_config, normalize_telegram_chat_id
from taskhub.telegram_webhook import _process_message, extract_start_payload_from_message_text
from taskhub.twitter_apify_client import _humanize_apify_twitter_error, apify_twitter_error_is_service_side
from taskhub.twitter_client import TwitterApiError
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


class TaskSerializationTests(TestCase):
    def test_serialize_task_adds_virtual_application_count_to_display_count(self):
        publisher = FrontendUser.objects.create(username="publisher_virtual", phone="13900000001", password="pass123456")
        applicant_one = FrontendUser.objects.create(
            username="applicant_virtual_1",
            phone="13900000002",
            password="pass123456",
        )
        applicant_two = FrontendUser.objects.create(
            username="applicant_virtual_2",
            phone="13900000003",
            password="pass123456",
        )
        task = Task.objects.create(
            publisher=publisher,
            title="虚拟参与人数任务",
            description="desc",
            applicants_limit=20,
            virtual_application_count=88,
            status=Task.STATUS_OPEN,
        )
        TaskApplication.objects.create(task=task, applicant=applicant_one, quoted_price="0.00")
        TaskApplication.objects.create(task=task, applicant=applicant_two, quoted_price="0.00")

        payload = serialize_task(task)

        self.assertEqual(payload["real_application_count"], 2)
        self.assertEqual(payload["virtual_application_count"], 88)
        self.assertEqual(payload["application_count"], 90)

    def test_serialize_task_includes_auto_growth_virtual_count(self):
        publisher = FrontendUser.objects.create(username="publisher_growth", phone="13900000011", password="pass123456")
        applicant = FrontendUser.objects.create(username="applicant_growth", phone="13900000012", password="pass123456")
        task = Task.objects.create(
            publisher=publisher,
            title="自动增长虚拟人数任务",
            description="desc",
            applicants_limit=20,
            virtual_application_count=30,
            virtual_auto_increment_count=12,
            status=Task.STATUS_OPEN,
        )
        TaskApplication.objects.create(task=task, applicant=applicant, quoted_price="0.00")

        payload = serialize_task(task)

        self.assertEqual(payload["real_application_count"], 1)
        self.assertEqual(payload["virtual_application_base_count"], 30)
        self.assertEqual(payload["virtual_application_auto_increment_count"], 12)
        self.assertEqual(payload["virtual_application_count"], 42)
        self.assertEqual(payload["application_count"], 43)

    def test_enrich_task_card_fields_uses_displayed_application_count_for_progress(self):
        publisher = FrontendUser.objects.create(
            username="publisher_progress",
            phone="13900000013",
            password="pass123456",
        )
        task = Task.objects.create(
            publisher=publisher,
            title="进度条任务",
            description="desc",
            applicants_limit=10,
            reward_usdt=Decimal("1.00"),
            reward_th_coin=Decimal("0.00"),
            virtual_application_count=4,
            virtual_auto_increment_count=3,
            status=Task.STATUS_OPEN,
        )

        payload = serialize_task(task)
        enrich_task_card_fields(task, payload)

        self.assertEqual(payload["application_count"], 7)
        self.assertEqual(payload["slot_progress_percent"], 70)


class VirtualApplicationGrowthTests(TestCase):
    @patch("taskhub.task_lifecycle.random.randint", side_effect=[2, 3])
    def test_advance_virtual_application_counts_adds_random_hourly_growth(self, mock_rand):
        publisher = FrontendUser.objects.create(
            username="publisher_virtual_growth",
            phone="13900000021",
            password="pass123456",
        )
        task = Task.objects.create(
            publisher=publisher,
            title="每小时自动增长",
            description="desc",
            applicants_limit=20,
            virtual_application_count=50,
            virtual_hourly_growth_min=1,
            virtual_hourly_growth_max=3,
            status=Task.STATUS_OPEN,
        )
        now = timezone.now()
        anchor = now - timedelta(hours=2, minutes=5)
        Task.objects.filter(pk=task.pk).update(created_at=anchor, updated_at=anchor)
        task.refresh_from_db()

        touched, added = advance_virtual_application_counts(now=now)

        task.refresh_from_db()
        self.assertEqual(touched, 1)
        self.assertEqual(added, 5)
        self.assertEqual(task.virtual_auto_increment_count, 5)
        self.assertEqual(task.display_virtual_application_count(), 55)
        self.assertEqual(task.virtual_growth_last_at, now)
        self.assertEqual(mock_rand.call_count, 2)

    @patch("taskhub.task_lifecycle.random.randint")
    def test_advance_virtual_application_counts_ignores_closed_tasks(self, mock_rand):
        publisher = FrontendUser.objects.create(
            username="publisher_virtual_growth_closed",
            phone="13900000022",
            password="pass123456",
        )
        task = Task.objects.create(
            publisher=publisher,
            title="关闭任务不增长",
            description="desc",
            applicants_limit=20,
            virtual_application_count=50,
            virtual_hourly_growth_min=1,
            virtual_hourly_growth_max=3,
            status=Task.STATUS_COMPLETED,
        )
        now = timezone.now()
        anchor = now - timedelta(hours=3)
        Task.objects.filter(pk=task.pk).update(created_at=anchor, updated_at=anchor)

        touched, added = advance_virtual_application_counts(now=now)

        task.refresh_from_db()
        self.assertEqual(touched, 0)
        self.assertEqual(added, 0)
        self.assertEqual(task.virtual_auto_increment_count, 0)
        mock_rand.assert_not_called()


class PlatformStatsVirtualConfigTests(TestCase):
    @patch(
        "taskhub.task_lifecycle.random.randint",
        side_effect=[2, 3, 4, 5, 6, 7, 0, 1, 5, 8, 9, 10],
    )
    def test_advance_virtual_platform_stats_applies_hourly_growth(self, mock_rand):
        config = PlatformStatsDisplayConfig.get()
        config.total_tasks_hourly_growth_min = 1
        config.total_tasks_hourly_growth_max = 3
        config.total_rewards_usdt_hourly_growth_min = Decimal("0.05")
        config.total_rewards_usdt_hourly_growth_max = Decimal("0.10")
        config.total_users_hourly_growth_min = 4
        config.total_users_hourly_growth_max = 8
        config.operating_days_hourly_growth_min = 0
        config.operating_days_hourly_growth_max = 2
        now = timezone.now()
        config.virtual_growth_last_at = now - timedelta(hours=2, minutes=8)
        config.save(
            update_fields=[
                "total_tasks_hourly_growth_min",
                "total_tasks_hourly_growth_max",
                "total_rewards_usdt_hourly_growth_min",
                "total_rewards_usdt_hourly_growth_max",
                "total_users_hourly_growth_min",
                "total_users_hourly_growth_max",
                "operating_days_hourly_growth_min",
                "operating_days_hourly_growth_max",
                "virtual_growth_last_at",
            ]
        )

        summary = advance_virtual_platform_stats(now=now)

        config.refresh_from_db()
        self.assertTrue(summary["updated"])
        self.assertEqual(summary["elapsed_hours"], 2)
        self.assertEqual(summary["added_total_tasks"], 5)
        self.assertEqual(summary["added_total_rewards_usdt"], Decimal("0.17"))
        self.assertEqual(summary["added_total_users"], 12)
        self.assertEqual(summary["added_operating_days"], 1)
        self.assertEqual(config.total_tasks_virtual_auto_increment, 5)
        self.assertEqual(config.total_rewards_usdt_virtual_auto_increment, Decimal("0.17"))
        self.assertEqual(config.total_users_virtual_auto_increment, 12)
        self.assertEqual(config.operating_days_virtual_auto_increment, 1)
        self.assertEqual(config.virtual_growth_last_at, now)
        self.assertEqual(mock_rand.call_count, 12)

    @override_settings(ONLINE_USERS_ACTIVE_WINDOW_MINUTES=5)
    def test_rankings_platform_stats_api_uses_realtime_online_users(self):
        now = timezone.now()
        FrontendUser.objects.create(
            username="rank_user_1",
            phone="13900001001",
            password="pass123456",
            last_seen_at=now - timedelta(minutes=1),
        )
        FrontendUser.objects.create(
            username="rank_user_2",
            phone="13900001002",
            password="pass123456",
            last_seen_at=now - timedelta(minutes=4, seconds=30),
        )
        FrontendUser.objects.create(
            username="rank_user_3",
            phone="13900001004",
            password="pass123456",
            last_seen_at=now - timedelta(minutes=9),
        )
        publisher = FrontendUser.objects.create(username="rank_publisher", phone="13900001003", password="pass123456")
        Task.objects.create(
            publisher=publisher,
            title="统计任务一",
            description="desc",
            status=Task.STATUS_OPEN,
        )
        Task.objects.create(
            publisher=publisher,
            title="统计任务二",
            description="desc",
            status=Task.STATUS_COMPLETED,
        )
        config = PlatformStatsDisplayConfig.get()
        config.total_tasks_virtual_base = 10
        config.total_rewards_usdt_virtual_base = Decimal("99.50")
        config.total_users_virtual_base = 20
        config.operating_days_virtual_base = 5
        config.total_tasks_virtual_auto_increment = 3
        config.total_rewards_usdt_virtual_auto_increment = Decimal("1.25")
        config.total_users_virtual_auto_increment = 4
        config.operating_days_virtual_auto_increment = 2
        config.save()

        response = self.client.get(reverse("taskhub-rankings-platform-stats"))

        self.assertEqual(response.status_code, 200)
        payload = response.json()["data"]
        self.assertEqual(payload["total_tasks"], 15)
        self.assertEqual(payload["total_rewards_issued_usdt"], "100.75")
        self.assertEqual(payload["total_users"], 28)
        self.assertEqual(payload["online_users"], 2)
        self.assertGreaterEqual(payload["operating_days"], 8)

    def test_me_ping_updates_last_seen_at(self):
        user = FrontendUser.objects.create(username="ping_user", phone="13900001005", password="pass123456")
        token = ApiToken.issue_for_user(user)

        response = self.client.post(
            reverse("taskhub-me-ping"),
            data="{}",
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token.key}",
        )

        self.assertEqual(response.status_code, 200)
        user.refresh_from_db()
        self.assertIsNotNone(user.last_seen_at)


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


class TelegramJoinTaskConfigTests(SimpleTestCase):
    def test_normalize_chat_id_accepts_public_channel_url(self):
        self.assertEqual(
            normalize_telegram_chat_id("https://t.me/taskhub_official"),
            "@taskhub_official",
        )
        self.assertEqual(
            normalize_telegram_chat_id("t.me/s/taskhub_official"),
            "@taskhub_official",
        )

    def test_normalize_chat_id_rejects_private_invite_link(self):
        self.assertIsNone(normalize_telegram_chat_id("https://t.me/+AbCdEf123"))
        self.assertIsNone(normalize_telegram_chat_id("https://t.me/joinchat/AbCdEf123"))

    def test_extract_chat_id_prefers_explicit_id_and_falls_back_to_public_invite(self):
        self.assertEqual(
            extract_telegram_chat_id_from_config({"telegram_chat_id": "-1001234567890"}),
            "-1001234567890",
        )
        self.assertEqual(
            extract_telegram_chat_id_from_config({"invite_link": "https://t.me/taskhub_official"}),
            "@taskhub_official",
        )
        self.assertIsNone(
            extract_telegram_chat_id_from_config({"invite_link": "https://t.me/+AbCdEf123"})
        )


class TwitterVerificationErrorTests(SimpleTestCase):
    def test_credit_depleted_error_is_actionable(self):
        ok, code, message, status = _twitter_verify_error(
            TwitterApiError(
                402,
                '{"title":"CreditsDepleted","detail":"Your enrolled account does not have any credits"}',
            ),
            action_label="转发",
            error_code=4320,
        )

        self.assertFalse(ok)
        self.assertEqual(code, 4320)
        self.assertEqual(status, 503)
        self.assertIn("额度已耗尽", message)

    def test_rate_limit_error_is_actionable(self):
        ok, code, message, status = _twitter_verify_error(
            TwitterApiError(429, '{"title":"Too Many Requests"}'),
            action_label="关注",
            error_code=4314,
        )

        self.assertFalse(ok)
        self.assertEqual(code, 4314)
        self.assertEqual(status, 429)
        self.assertIn("过于频繁", message)

    def test_apify_twitter_auth_error_is_humanized(self):
        message = _humanize_apify_twitter_error(
            "User was not found or authentication token is not valid",
            action_label="转发",
        )

        self.assertEqual(message, "Twitter Apify 校验服务鉴权失败，请联系管理员检查 Apify Token。")

    def test_apify_twitter_cookie_error_is_service_side(self):
        self.assertTrue(apify_twitter_error_is_service_side("auth_token cookie is required"))
        self.assertFalse(apify_twitter_error_is_service_side("并未检测到转发，请先完成转发后再试。"))


class ReferralRewardTests(TestCase):
    def test_task_reward_also_grants_referrer_reward_from_admin_config(self):
        referrer = FrontendUser.objects.create(username="parent_agent", phone="13800000001", password="pass123456")
        child = FrontendUser.objects.create(
            username="child_member",
            phone="13800000002",
            password="pass123456",
            referrer=referrer,
        )
        publisher = FrontendUser.objects.create(username="publisher_1", phone="13800000003", password="pass123456")
        task = Task.objects.create(
            publisher=publisher,
            title="测试任务",
            description="desc",
            reward_usdt=Decimal("12.00"),
            reward_th_coin=Decimal("2.00"),
            applicants_limit=1,
            status=Task.STATUS_OPEN,
        )
        app = TaskApplication.objects.create(
            task=task,
            applicant=child,
            status=TaskApplication.STATUS_ACCEPTED,
            quoted_price="0.00",
        )
        ReferralRewardConfig.objects.create(direct_invite_rate="0.2500")

        result = grant_task_completion_reward(app)

        child_wallet = Wallet.objects.get(user=child)
        referrer_wallet = Wallet.objects.get(user=referrer)
        self.assertEqual(str(child_wallet.balance), "12.00")
        self.assertEqual(str(child_wallet.frozen), "2.00")
        self.assertEqual(str(referrer_wallet.balance), "3.00")
        self.assertEqual(str(referrer_wallet.frozen), "0.50")
        self.assertEqual(result["referrer_reward_usdt"], "3.00")
        self.assertEqual(result["referrer_reward_th_coin"], "0.50")
        self.assertTrue(
            Transaction.objects.filter(
                wallet=referrer_wallet,
                change_type="reward",
                asset=Transaction.ASSET_USDT,
                amount="3.00",
            ).exists()
        )
        self.assertTrue(
            Transaction.objects.filter(
                wallet=referrer_wallet,
                change_type="reward",
                asset=Transaction.ASSET_TH_COIN,
                amount="0.50",
            ).exists()
        )

    def test_task_reward_grants_second_level_referrer_reward(self):
        grandparent = FrontendUser.objects.create(username="root_agent", phone="13800000004", password="pass123456")
        referrer = FrontendUser.objects.create(
            username="parent_agent_2",
            phone="13800000005",
            password="pass123456",
            referrer=grandparent,
        )
        child = FrontendUser.objects.create(
            username="child_member_2",
            phone="13800000006",
            password="pass123456",
            referrer=referrer,
        )
        publisher = FrontendUser.objects.create(username="publisher_2", phone="13800000007", password="pass123456")
        task = Task.objects.create(
            publisher=publisher,
            title="二级返佣测试",
            description="desc",
            reward_usdt=Decimal("10.00"),
            applicants_limit=1,
            status=Task.STATUS_OPEN,
        )
        app = TaskApplication.objects.create(
            task=task,
            applicant=child,
            status=TaskApplication.STATUS_ACCEPTED,
            quoted_price="0.00",
        )
        ReferralRewardConfig.objects.create(direct_invite_rate="0.2000", second_task_rate="0.1000")

        result = grant_task_completion_reward(app)

        referrer_wallet = Wallet.objects.get(user=referrer)
        grandparent_wallet = Wallet.objects.get(user=grandparent)
        self.assertEqual(str(referrer_wallet.balance), "2.00")
        self.assertEqual(str(grandparent_wallet.balance), "1.00")
        self.assertEqual(result["referrer_reward_usdt"], "3.00")
        self.assertEqual(
            [(item["level"], item["amount"]) for item in result["referrer_rewards"]],
            [(1, "2.00"), (2, "1.00")],
        )

    def test_task_reward_grants_th_coin_referrer_rewards(self):
        grandparent = FrontendUser.objects.create(username="root_agent_th", phone="13800000011", password="pass123456")
        referrer = FrontendUser.objects.create(
            username="parent_agent_th",
            phone="13800000012",
            password="pass123456",
            referrer=grandparent,
        )
        child = FrontendUser.objects.create(
            username="child_member_th",
            phone="13800000013",
            password="pass123456",
            referrer=referrer,
        )
        publisher = FrontendUser.objects.create(username="publisher_th", phone="13800000014", password="pass123456")
        task = Task.objects.create(
            publisher=publisher,
            title="TH 分佣测试",
            description="desc",
            reward_th_coin=Decimal("10.00"),
            applicants_limit=1,
            status=Task.STATUS_OPEN,
        )
        app = TaskApplication.objects.create(
            task=task,
            applicant=child,
            status=TaskApplication.STATUS_ACCEPTED,
            quoted_price="0.00",
        )
        ReferralRewardConfig.objects.create(direct_invite_rate="0.2000", second_task_rate="0.1000")

        result = grant_task_completion_reward(app)

        referrer_wallet = Wallet.objects.get(user=referrer)
        grandparent_wallet = Wallet.objects.get(user=grandparent)
        self.assertEqual(str(referrer_wallet.balance), "0.00")
        self.assertEqual(str(referrer_wallet.frozen), "2.00")
        self.assertEqual(str(grandparent_wallet.balance), "0.00")
        self.assertEqual(str(grandparent_wallet.frozen), "1.00")
        self.assertEqual(result["referrer_reward_usdt"], "0.00")
        self.assertEqual(result["referrer_reward_th_coin"], "3.00")
        self.assertEqual(
            [(item["level"], item["amount"], item["asset"]) for item in result["referrer_rewards"]],
            [
                (1, "2.00", Transaction.ASSET_TH_COIN),
                (2, "1.00", Transaction.ASSET_TH_COIN),
            ],
        )

    def test_recharge_transaction_no_longer_grants_two_level_commission(self):
        grandparent = FrontendUser.objects.create(username="recharge_root", phone="13800000008", password="pass123456")
        referrer = FrontendUser.objects.create(
            username="recharge_parent",
            phone="13800000009",
            password="pass123456",
            referrer=grandparent,
        )
        child = FrontendUser.objects.create(
            username="recharge_child",
            phone="13800000010",
            password="pass123456",
            referrer=referrer,
        )
        ReferralRewardConfig.objects.create(direct_recharge_rate="0.2000", second_recharge_rate="0.1000")
        Wallet.objects.get_or_create(user=child)
        child_wallet = Wallet.objects.get(user=child)

        Transaction.objects.create(
            wallet=child_wallet,
            asset=Transaction.ASSET_USDT,
            amount=Decimal("100.00"),
            before_balance=Decimal("0.00"),
            after_balance=Decimal("100.00"),
            change_type="recharge",
            remark="测试充值",
        )

        self.assertFalse(Wallet.objects.filter(user=referrer).exists())
        self.assertFalse(Wallet.objects.filter(user=grandparent).exists())


class ProfileLanguagePreferenceTests(TestCase):
    def test_patch_profile_updates_preferred_language(self):
        user = FrontendUser.objects.create(
            username="lang_user",
            phone="13800000021",
            password="pass123456",
        )
        token = ApiToken.issue_for_user(user)

        response = self.client.patch(
            reverse("taskhub-profile"),
            data={"preferred_language": "pt"},
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token.key}",
        )

        self.assertEqual(response.status_code, 200)
        user.refresh_from_db()
        self.assertEqual(user.preferred_language, "pt-BR")
        self.assertEqual(response.json()["data"]["user"]["preferred_language"], "pt-BR")


class RechargeAndMembershipTests(TestCase):
    _TEST_MNEMONIC = "test test test test test test test test test test test junk"
    _TEST_COLLECTOR_PRIVATE_KEY = "ac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"

    def test_evm_transfer_topic_is_0x_prefixed(self):
        self.assertTrue(_EVM_TRANSFER_TOPIC.startswith("0x"))

    def test_recharge_network_prefers_explicit_sweep_destination_address(self):
        network = RechargeNetworkConfig(
            chain=RechargeNetworkConfig.CHAIN_ERC20,
            collector_address="0x0000000000000000000000000000000000001000",
            sweep_destination_address="0x0000000000000000000000000000000000002000",
        )

        self.assertEqual(
            network.effective_sweep_destination_address,
            "0x0000000000000000000000000000000000002000",
        )

    def test_get_recharges_returns_dedicated_address(self):
        user = FrontendUser.objects.create(username="recharge_api_user", phone="13800000041", password="pass123456")
        token = ApiToken.issue_for_user(user)
        RechargeNetworkConfig.objects.update_or_create(
            chain=RechargeNetworkConfig.CHAIN_ERC20,
            defaults={
                "display_name": "USDT-ERC20",
                "token_contract_address": "0xdAC17F958D2ee523a2206206994597C13D831ec7",
                "rpc_endpoint": "https://eth.llamarpc.com",
                "master_mnemonic": self._TEST_MNEMONIC,
                "collector_address": "0x0000000000000000000000000000000000001000",
                "sweep_destination_address": "0x0000000000000000000000000000000000001000",
                "collector_private_key": self._TEST_COLLECTOR_PRIVATE_KEY,
                "min_amount_usdt": Decimal("5.00"),
                "confirmations_required": 6,
                "is_active": True,
            },
        )

        response = self.client.get(
            reverse("taskhub-me-recharges"),
            HTTP_AUTHORIZATION=f"Bearer {token.key}",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()["data"]
        target = next(row for row in payload["networks"] if row["chain"] == RechargeNetworkConfig.CHAIN_ERC20)
        self.assertTrue(target["deposit_address"].startswith("0x"))
        self.assertTrue(target["is_configured"])
        self.assertTrue(UserRechargeAddress.objects.filter(user=user, network__chain="ERC20").exists())

    def test_get_recharges_handles_invalid_auto_config_gracefully(self):
        user = FrontendUser.objects.create(username="recharge_bad_cfg_user", phone="13800000044", password="pass123456")
        token = ApiToken.issue_for_user(user)
        RechargeNetworkConfig.objects.update_or_create(
            chain=RechargeNetworkConfig.CHAIN_TRC20,
            defaults={
                "display_name": "USDT-TRC20",
                "token_contract_address": "TXLAQ63Xg1NAzckPwKHvzw7CSEmLMEqcdj",
                "rpc_endpoint": "https://api.trongrid.io",
                "master_mnemonic": "not a valid mnemonic at all",
                "collector_address": "T9yD14Nj9j7xAB4dbGeiX9h8unkKHxuWwb",
                "sweep_destination_address": "T9yD14Nj9j7xAB4dbGeiX9h8unkKHxuWwb",
                "collector_private_key": self._TEST_COLLECTOR_PRIVATE_KEY,
                "min_amount_usdt": Decimal("5.00"),
                "confirmations_required": 20,
                "is_active": True,
            },
        )

        response = self.client.get(
            reverse("taskhub-me-recharges"),
            HTTP_AUTHORIZATION=f"Bearer {token.key}",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()["data"]
        target = next(row for row in payload["networks"] if row["chain"] == RechargeNetworkConfig.CHAIN_TRC20)
        self.assertEqual(target["deposit_address"], "")
        self.assertFalse(target["is_configured"])
        self.assertIn("生成失败", target["config_error"])
        self.assertFalse(UserRechargeAddress.objects.filter(user=user, network__chain="TRC20").exists())

    def test_get_recharges_accepts_tron_hex_address_and_multiline_private_key(self):
        user = FrontendUser.objects.create(username="recharge_tron_user", phone="13800000045", password="pass123456")
        token = ApiToken.issue_for_user(user)
        _, tron_hex = _tron_base58_from_private_key(self._TEST_COLLECTOR_PRIVATE_KEY)
        RechargeNetworkConfig.objects.update_or_create(
            chain=RechargeNetworkConfig.CHAIN_TRC20,
            defaults={
                "display_name": "USDT-TRC20",
                "token_contract_address": "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t",
                "rpc_endpoint": "https://api.trongrid.io",
                "master_mnemonic": "test  test\ntest   test test test\ntest test test test test junk",
                "collector_address": f"  {tron_hex}  ",
                "sweep_destination_address": f"  {tron_hex}  ",
                "collector_private_key": f"  0x{self._TEST_COLLECTOR_PRIVATE_KEY[:32]}\n{self._TEST_COLLECTOR_PRIVATE_KEY[32:]}  ",
                "min_amount_usdt": Decimal("5.00"),
                "confirmations_required": 20,
                "is_active": True,
            },
        )

        response = self.client.get(
            reverse("taskhub-me-recharges"),
            HTTP_AUTHORIZATION=f"Bearer {token.key}",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()["data"]
        target = next(row for row in payload["networks"] if row["chain"] == RechargeNetworkConfig.CHAIN_TRC20)
        self.assertTrue(target["deposit_address"].startswith("T"))
        self.assertTrue(target["is_configured"])
        self.assertTrue(UserRechargeAddress.objects.filter(user=user, network__chain="TRC20").exists())

    @patch("wallets.auto_recharge.EvmUsdtClient")
    def test_sync_network_recharges_detects_and_credits_confirmed_transfer(self, mock_client_cls):
        user = FrontendUser.objects.create(username="recharge_sync_user", phone="13800000043", password="pass123456")
        network, _ = RechargeNetworkConfig.objects.update_or_create(
            chain=RechargeNetworkConfig.CHAIN_ERC20,
            defaults={
                "display_name": "USDT-ERC20",
                "token_contract_address": "0xdAC17F958D2ee523a2206206994597C13D831ec7",
                "rpc_endpoint": "https://eth.llamarpc.com",
                "master_mnemonic": self._TEST_MNEMONIC,
                "collector_address": "0x0000000000000000000000000000000000001000",
                "sweep_destination_address": "0x0000000000000000000000000000000000001000",
                "collector_private_key": self._TEST_COLLECTOR_PRIVATE_KEY,
                "min_amount_usdt": Decimal("1.00"),
                "confirmations_required": 2,
                "is_active": True,
            },
        )
        addr = ensure_user_recharge_address(user, network)
        self.assertIsNotNone(addr)

        mock_client = mock_client_cls.return_value
        mock_client.latest_block.return_value = 120
        mock_client.list_new_transfers.return_value = [
            DetectedTransfer(
                tx_hash="0xabc123",
                log_index=0,
                from_address="0x0000000000000000000000000000000000002000",
                to_address=addr.address,
                amount=Decimal("12.50"),
                block_number=118,
                confirmations=3,
                raw_payload={"demo": True},
            )
        ]

        stats = sync_network_recharges(network)

        self.assertEqual(stats["credited"], 1)
        req = RechargeRequest.objects.get(user=user, tx_hash="0xabc123", source_type=RechargeRequest.SOURCE_AUTO)
        self.assertEqual(req.status, RechargeRequest.STATUS_COMPLETED)
        self.assertIsNotNone(req.credited_transaction_id)
        wallet = Wallet.objects.get(user=user)
        self.assertEqual(str(wallet.balance), "12.50")

    @patch("wallets.auto_recharge.EvmUsdtClient")
    def test_sync_network_recharges_uses_stable_scan_block(self, mock_client_cls):
        user = FrontendUser.objects.create(username="recharge_sync_safe_user", phone="13800000046", password="pass123456")
        network, _ = RechargeNetworkConfig.objects.update_or_create(
            chain=RechargeNetworkConfig.CHAIN_ERC20,
            defaults={
                "display_name": "USDT-ERC20",
                "token_contract_address": "0xdAC17F958D2ee523a2206206994597C13D831ec7",
                "rpc_endpoint": "https://eth.llamarpc.com",
                "master_mnemonic": self._TEST_MNEMONIC,
                "collector_address": "0x0000000000000000000000000000000000001000",
                "sweep_destination_address": "0x0000000000000000000000000000000000001000",
                "collector_private_key": self._TEST_COLLECTOR_PRIVATE_KEY,
                "min_amount_usdt": Decimal("1.00"),
                "confirmations_required": 2,
                "is_active": True,
            },
        )
        ensure_user_recharge_address(user, network)

        mock_client = mock_client_cls.return_value
        mock_client.latest_block.return_value = 120
        mock_client.stable_scan_to_block.return_value = 114
        mock_client.list_new_transfers.return_value = []

        stats = sync_network_recharges(network)

        self.assertEqual(stats["detected"], 0)
        mock_client.stable_scan_to_block.assert_called_once_with(from_block=0, requested_to_block=120)
        mock_client.list_new_transfers.assert_called_once()
        self.assertEqual(mock_client.list_new_transfers.call_args.kwargs["to_block"], 114)
        network.refresh_from_db()
        self.assertEqual(network.scan_from_block, 115)

    def test_probe_log_scanning_uses_safe_latest_window(self):
        client = object.__new__(EvmUsdtClient)
        client.network = RechargeNetworkConfig(
            chain=RechargeNetworkConfig.CHAIN_ERC20,
            token_contract_address="0xdAC17F958D2ee523a2206206994597C13D831ec7",
        )
        client.w3 = MagicMock()
        client.latest_block = MagicMock(return_value=120)
        client.stable_scan_to_block = MagicMock(return_value=114)
        client.w3.eth.get_logs.return_value = []

        scanned_to = EvmUsdtClient.probe_log_scanning(client)

        self.assertEqual(scanned_to, 114)
        client.stable_scan_to_block.assert_called_once_with(from_block=119, requested_to_block=120)
        kwargs = client.w3.eth.get_logs.call_args.args[0]
        self.assertEqual(kwargs["fromBlock"], 113)
        self.assertEqual(kwargs["toBlock"], 114)

    def test_user_can_purchase_membership_with_wallet_balance(self):
        user = FrontendUser.objects.create(
            username="vip_buyer",
            phone="13800000042",
            password="pass123456",
            membership_level=1,
        )
        token = ApiToken.issue_for_user(user)
        wallet = Wallet.objects.create(user=user, balance=Decimal("80.00"))
        MembershipLevelConfig.objects.update_or_create(
            level=2,
            defaults={
                "name": "VIP2",
                "join_fee_usdt": Decimal("50.00"),
                "can_claim_free_tasks": True,
                "can_claim_official_tasks": True,
                "is_active": True,
            },
        )

        response = self.client.post(
            reverse("taskhub-me-membership-purchase"),
            data={"level": 2},
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token.key}",
        )

        self.assertEqual(response.status_code, 200)
        user.refresh_from_db()
        wallet.refresh_from_db()
        self.assertEqual(user.membership_level, 2)
        self.assertEqual(str(wallet.balance), "30.00")
        self.assertTrue(
            Transaction.objects.filter(
                wallet=wallet,
                change_type="cost",
                asset=Transaction.ASSET_USDT,
                amount="-50.00",
            ).exists()
        )

    def test_membership_purchase_grants_two_level_rebate_with_burn_cap(self):
        grandparent = FrontendUser.objects.create(
            username="vip_root",
            phone="13800000043",
            password="pass123456",
            membership_level=3,
        )
        referrer = FrontendUser.objects.create(
            username="vip_parent",
            phone="13800000044",
            password="pass123456",
            membership_level=2,
            referrer=grandparent,
        )
        child = FrontendUser.objects.create(
            username="vip_child",
            phone="13800000045",
            password="pass123456",
            membership_level=1,
            referrer=referrer,
        )
        token = ApiToken.issue_for_user(child)
        Wallet.objects.create(user=child, balance=Decimal("1000.00"))
        ReferralRewardConfig.objects.update_or_create(
            id=1,
            defaults={
                "direct_invite_rate": Decimal("0.20"),
                "second_task_rate": Decimal("0.10"),
                "direct_recharge_rate": Decimal("0.20"),
                "second_recharge_rate": Decimal("0.10"),
            },
        )
        MembershipLevelConfig.objects.update_or_create(
            level=1,
            defaults={
                "name": "VIP1",
                "join_fee_usdt": Decimal("10.00"),
                "can_claim_free_tasks": True,
                "can_claim_official_tasks": True,
                "is_active": True,
            },
        )
        MembershipLevelConfig.objects.update_or_create(
            level=2,
            defaults={
                "name": "VIP2",
                "join_fee_usdt": Decimal("100.00"),
                "can_claim_free_tasks": True,
                "can_claim_official_tasks": True,
                "is_active": True,
            },
        )
        MembershipLevelConfig.objects.update_or_create(
            level=3,
            defaults={
                "name": "VIP3",
                "join_fee_usdt": Decimal("1000.00"),
                "can_claim_free_tasks": True,
                "can_claim_official_tasks": True,
                "is_active": True,
            },
        )

        response = self.client.post(
            reverse("taskhub-me-membership-purchase"),
            data={"level": 3},
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token.key}",
        )

        self.assertEqual(response.status_code, 200)
        child.refresh_from_db()
        self.assertEqual(child.membership_level, 3)
        self.assertEqual(str(Wallet.objects.get(user=child).balance), "0.00")
        self.assertEqual(str(Wallet.objects.get(user=referrer).balance), "20.00")
        self.assertEqual(str(Wallet.objects.get(user=grandparent).balance), "100.00")
        rewards = response.json()["data"]["referral_rewards"]
        self.assertEqual(
            [(item["level"], item["amount"], item["reward_base_amount"], item["burned"]) for item in rewards],
            [(1, "20.00", "100.00", True), (2, "100.00", "1000.00", False)],
        )

    def test_membership_purchase_skips_v0_uplink_rebate(self):
        grandparent = FrontendUser.objects.create(
            username="vip_zero_root",
            phone="13800000046",
            password="pass123456",
            membership_level=0,
        )
        referrer = FrontendUser.objects.create(
            username="vip_level_1_parent",
            phone="13800000047",
            password="pass123456",
            membership_level=1,
            referrer=grandparent,
        )
        child = FrontendUser.objects.create(
            username="vip_level_0_child",
            phone="13800000048",
            password="pass123456",
            membership_level=0,
            referrer=referrer,
        )
        token = ApiToken.issue_for_user(child)
        Wallet.objects.create(user=child, balance=Decimal("1000.00"))
        ReferralRewardConfig.objects.update_or_create(
            id=1,
            defaults={
                "direct_invite_rate": Decimal("0.20"),
                "second_task_rate": Decimal("0.10"),
                "direct_recharge_rate": Decimal("0.20"),
                "second_recharge_rate": Decimal("0.10"),
            },
        )
        MembershipLevelConfig.objects.update_or_create(
            level=0,
            defaults={
                "name": "VIP0",
                "join_fee_usdt": Decimal("0.00"),
                "can_claim_free_tasks": True,
                "can_claim_official_tasks": False,
                "is_active": True,
            },
        )
        MembershipLevelConfig.objects.update_or_create(
            level=1,
            defaults={
                "name": "VIP1",
                "join_fee_usdt": Decimal("100.00"),
                "can_claim_free_tasks": True,
                "can_claim_official_tasks": True,
                "is_active": True,
            },
        )
        MembershipLevelConfig.objects.update_or_create(
            level=3,
            defaults={
                "name": "VIP3",
                "join_fee_usdt": Decimal("1000.00"),
                "can_claim_free_tasks": True,
                "can_claim_official_tasks": True,
                "is_active": True,
            },
        )

        response = self.client.post(
            reverse("taskhub-me-membership-purchase"),
            data={"level": 3},
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token.key}",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(str(Wallet.objects.get(user=referrer).balance), "20.00")
        self.assertFalse(Wallet.objects.filter(user=grandparent).exists())


class AgentAdminLoginTests(TestCase):
    def test_agent_profile_uses_frontend_member_credentials_to_login(self):
        root_user = FrontendUser.objects.create(
            username="agent_owner",
            phone="13800000011",
            password="pass123456",
        )
        profile = AgentProfile.objects.create(root_user=root_user, include_self=True, is_active=True)

        self.assertIsNotNone(profile.backend_user_id)
        self.assertEqual(profile.backend_user.username, f"agent_member_{root_user.id}")
        self.assertTrue(profile.backend_user.is_staff)
        self.assertFalse(profile.backend_user.has_usable_password())

        response = self.client.post(
            reverse("agent_admin:login"),
            {"account": "agent_owner", "password": "pass123456"},
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], reverse("agent_admin:index"))
        session = self.client.session
        self.assertEqual(session[AGENT_ROOT_USER_SESSION_KEY], root_user.id)
        home = self.client.get(reverse("agent_admin:index"))
        self.assertEqual(home.status_code, 200)

    def test_superuser_cannot_directly_enter_agent_admin(self):
        admin_user = get_user_model().objects.create_superuser(
            username="main_admin",
            email="admin@example.com",
            password="adminpass123",
        )
        self.client.force_login(admin_user)

        response = self.client.get(reverse("agent_admin:index"))

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("agent_admin:login"), response.headers["Location"])


class VipTaskZoneTests(TestCase):
    def setUp(self):
        self.publisher = FrontendUser.objects.create(
            username="vip_task_publisher",
            phone="13800000120",
            password="pass123456",
        )
        self.vip1_user = FrontendUser.objects.create(
            username="vip_level_1",
            phone="13800000121",
            password="pass123456",
            membership_level=1,
        )
        self.vip0_user = FrontendUser.objects.create(
            username="vip_level_0",
            phone="13800000122",
            password="pass123456",
            membership_level=0,
        )
        self.vip1_token = ApiToken.issue_for_user(self.vip1_user)
        self.vip0_token = ApiToken.issue_for_user(self.vip0_user)
        MembershipLevelConfig.objects.update_or_create(
            level=0,
            defaults={
                "name": "VIP0",
                "join_fee_usdt": Decimal("0"),
                "can_claim_free_tasks": True,
                "can_claim_official_tasks": False,
                "daily_official_task_limit": None,
                "withdraw_fee_rate": Decimal("0.20"),
                "is_active": True,
            },
        )
        MembershipLevelConfig.objects.update_or_create(
            level=1,
            defaults={
                "name": "VIP1",
                "join_fee_usdt": Decimal("50"),
                "can_claim_free_tasks": True,
                "can_claim_official_tasks": True,
                "daily_official_task_limit": 1,
                "withdraw_fee_rate": Decimal("0.10"),
                "is_active": True,
            },
        )

    def _make_task(self, title: str, *, vip: bool) -> Task:
        return Task.objects.create(
            publisher=self.publisher,
            title=title,
            description="任务说明",
            reward_usdt=Decimal("1.00"),
            reward_th_coin=Decimal("0.00"),
            applicants_limit=10,
            status=Task.STATUS_OPEN,
            is_vip_exclusive=vip,
        )

    def test_task_center_splits_vip_zone_and_public_tasks(self):
        vip_task = self._make_task("VIP 专属任务", vip=True)
        public_task = self._make_task("普通任务", vip=False)

        response = self.client.get(
            reverse("taskhub-tasks-center"),
            HTTP_AUTHORIZATION=f"Bearer {self.vip1_token.key}",
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual([item["id"] for item in data["vip_zone"]["items"]], [vip_task.id])
        self.assertEqual([item["id"] for item in data["available"]["items"]], [public_task.id])
        self.assertTrue(data["vip_zone"]["summary"]["has_access"])
        self.assertEqual(data["vip_zone"]["summary"]["daily_limit"], 1)

    def test_vip0_user_cannot_apply_vip_task(self):
        vip_task = self._make_task("VIP 限定任务", vip=True)

        response = self.client.post(
            reverse("taskhub-task-apply", args=[vip_task.id]),
            data="{}",
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {self.vip0_token.key}",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], 4401)
        self.assertIn("VIP1", response.json()["message"])

    def test_vip_daily_limit_blocks_second_new_vip_task(self):
        first_vip_task = self._make_task("VIP 任务 1", vip=True)
        second_vip_task = self._make_task("VIP 任务 2", vip=True)
        TaskApplication.objects.create(
            task=first_vip_task,
            applicant=self.vip1_user,
            status=TaskApplication.STATUS_ACCEPTED,
            decided_at=timezone.now(),
            quoted_price="0.00",
        )

        response = self.client.post(
            reverse("taskhub-task-apply", args=[second_vip_task.id]),
            data="{}",
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {self.vip1_token.key}",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], 4402)
        self.assertIn("已用完", response.json()["message"])

    def test_cancelled_vip_task_does_not_consume_daily_limit(self):
        cancelled_vip_task = self._make_task("VIP 已取消任务", vip=True)
        next_vip_task = self._make_task("VIP 后续任务", vip=True)
        TaskApplication.objects.create(
            task=cancelled_vip_task,
            applicant=self.vip1_user,
            status=TaskApplication.STATUS_CANCELLED,
            quoted_price="0.00",
        )

        response = self.client.post(
            reverse("taskhub-task-apply", args=[next_vip_task.id]),
            data="{}",
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {self.vip1_token.key}",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["message"], "报名成功")

    def test_completed_mandatory_vip_task_still_consumes_vip_quota(self):
        mandatory_vip_task = self._make_task("首页必做 VIP 任务", vip=True)
        mandatory_vip_task.is_mandatory = True
        mandatory_vip_task.save(update_fields=["is_mandatory", "updated_at"])
        completed_at = timezone.now() - timedelta(minutes=1)
        TaskApplication.objects.create(
            task=mandatory_vip_task,
            applicant=self.vip1_user,
            status=TaskApplication.STATUS_ACCEPTED,
            self_verified_at=completed_at,
            decided_at=completed_at,
            quoted_price="0.00",
        )

        response = self.client.get(
            reverse("taskhub-tasks-center"),
            HTTP_AUTHORIZATION=f"Bearer {self.vip1_token.key}",
        )

        self.assertEqual(response.status_code, 200)
        summary = response.json()["data"]["vip_zone"]["summary"]
        self.assertEqual(summary["used_today"], 1)
        self.assertEqual(summary["remaining_today"], 0)


class TaskRecordFlowTests(TestCase):
    def setUp(self):
        self.publisher = FrontendUser.objects.create(
            username="record_task_publisher",
            phone="13800000130",
            password="pass123456",
        )
        self.user = FrontendUser.objects.create(
            username="record_task_user",
            phone="13800000131",
            password="pass123456",
        )
        self.token = ApiToken.issue_for_user(self.user)

    def _open_task(self, *, interaction_type=Task.INTERACTION_JOIN_COMMUNITY, verification_mode=None) -> Task:
        return Task.objects.create(
            publisher=self.publisher,
            title="记录测试任务",
            description="任务说明",
            reward_usdt=Decimal("1.00"),
            reward_th_coin=Decimal("0.00"),
            applicants_limit=10,
            status=Task.STATUS_OPEN,
            interaction_type=interaction_type,
            verification_mode=verification_mode,
        )

    def test_pending_join_task_record_can_continue(self):
        task = self._open_task(interaction_type=Task.INTERACTION_JOIN_COMMUNITY)
        TaskApplication.objects.create(
            task=task,
            applicant=self.user,
            status=TaskApplication.STATUS_PENDING,
            quoted_price="0.00",
        )

        response = self.client.get(
            reverse("taskhub-my-task-records"),
            HTTP_AUTHORIZATION=f"Bearer {self.token.key}",
        )

        self.assertEqual(response.status_code, 200)
        item = response.json()["data"]["items"][0]
        self.assertEqual(item["record_status"], "under_review")
        self.assertTrue(item["can_continue"])

    @override_settings(TASK_PENDING_APPLICATION_TIMEOUT_MINUTES=5)
    def test_stale_pending_task_auto_expires_in_records(self):
        task = self._open_task(interaction_type=Task.INTERACTION_JOIN_COMMUNITY)
        app = TaskApplication.objects.create(
            task=task,
            applicant=self.user,
            status=TaskApplication.STATUS_PENDING,
            quoted_price="0.00",
        )
        stale_at = timezone.now() - timedelta(minutes=6)
        TaskApplication.objects.filter(pk=app.pk).update(created_at=stale_at, updated_at=stale_at)

        response = self.client.get(
            reverse("taskhub-my-task-records"),
            HTTP_AUTHORIZATION=f"Bearer {self.token.key}",
        )

        self.assertEqual(response.status_code, 200)
        app.refresh_from_db()
        self.assertEqual(app.status, TaskApplication.STATUS_CANCELLED)
        item = response.json()["data"]["items"][0]
        self.assertEqual(item["record_status"], "invalid")
        self.assertFalse(item["can_continue"])

    @override_settings(TASK_PENDING_APPLICATION_TIMEOUT_MINUTES=5)
    def test_pending_task_uses_updated_at_as_last_activity_for_expiry(self):
        task = self._open_task(interaction_type=Task.INTERACTION_JOIN_COMMUNITY)
        app = TaskApplication.objects.create(
            task=task,
            applicant=self.user,
            status=TaskApplication.STATUS_PENDING,
            quoted_price="0.00",
        )
        created_at = timezone.now() - timedelta(minutes=8)
        active_at = timezone.now() - timedelta(minutes=2)
        TaskApplication.objects.filter(pk=app.pk).update(created_at=created_at, updated_at=active_at)

        response = self.client.get(
            reverse("taskhub-my-task-records"),
            HTTP_AUTHORIZATION=f"Bearer {self.token.key}",
        )

        self.assertEqual(response.status_code, 200)
        app.refresh_from_db()
        self.assertEqual(app.status, TaskApplication.STATUS_PENDING)
        item = response.json()["data"]["items"][0]
        self.assertNotEqual(item["record_status"], "invalid")

class SocialActionTaskTests(TestCase):
    def _create_user_pair(self):
        publisher = FrontendUser.objects.create(
            username="social_publisher",
            phone="13800000031",
            password="pass123456",
        )
        applicant = FrontendUser.objects.create(
            username="social_user",
            phone="13800000032",
            password="pass123456",
        )
        return publisher, applicant, ApiToken.issue_for_user(applicant)

    def _bind_platform_account(self, *, publisher, applicant, platform, username="taskhub_user"):
        binding_task = Task.objects.create(
            publisher=publisher,
            title=f"绑定 {platform}",
            description="绑定账号",
            interaction_type=Task.INTERACTION_ACCOUNT_BINDING,
            binding_platform=platform,
            reward_usdt=Decimal("0.00"),
            reward_th_coin=Decimal("0.00"),
            applicants_limit=1,
            status=Task.STATUS_OPEN,
        )
        return TaskApplication.objects.create(
            task=binding_task,
            applicant=applicant,
            status=TaskApplication.STATUS_ACCEPTED,
            bound_username=username,
            quoted_price="0.00",
        )

    def test_social_action_verify_rejects_user_without_platform_binding(self):
        publisher, applicant, token = self._create_user_pair()
        task = Task.objects.create(
            publisher=publisher,
            title="关注 Twitter",
            description="打开链接后关注官方账号",
            interaction_type=Task.INTERACTION_FOLLOW,
            binding_platform=Task.BINDING_TWITTER,
            interaction_config={"target_follow_username": "taskhub_official"},
            reward_usdt=Decimal("0.50"),
            reward_th_coin=Decimal("1.00"),
            applicants_limit=5,
            status=Task.STATUS_OPEN,
        )
        application = TaskApplication.objects.create(
            task=task,
            applicant=applicant,
            status=TaskApplication.STATUS_PENDING,
            quoted_price="0.00",
        )

        response = self.client.post(
            reverse("taskhub-application-verify-social-action", args=[application.id]),
            data="{}",
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token.key}",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], 4311)
        application.refresh_from_db()
        self.assertEqual(application.status, TaskApplication.STATUS_PENDING)

    @patch("taskhub.api_views.user_follows_username_via_apify")
    @patch("taskhub.api_views.apify_twitter_follow_configured")
    def test_twitter_follow_task_rejects_when_follow_not_detected(self, mock_configured, mock_follows):
        publisher, applicant, token = self._create_user_pair()
        self._bind_platform_account(
            publisher=publisher,
            applicant=applicant,
            platform=Task.BINDING_TWITTER,
            username="social_user_x",
        )
        mock_configured.return_value = True
        mock_follows.return_value = (False, "并未检测到关注，请先完成关注后再试。")
        task = Task.objects.create(
            publisher=publisher,
            title="关注 Twitter",
            description="打开链接后关注官方账号",
            interaction_type=Task.INTERACTION_FOLLOW,
            binding_platform=Task.BINDING_TWITTER,
            interaction_config={"target_follow_username": "taskhub_official"},
            reward_usdt=Decimal("0.50"),
            reward_th_coin=Decimal("1.00"),
            applicants_limit=5,
            status=Task.STATUS_OPEN,
        )
        application = TaskApplication.objects.create(
            task=task,
            applicant=applicant,
            status=TaskApplication.STATUS_PENDING,
            quoted_price="0.00",
        )

        response = self.client.post(
            reverse("taskhub-application-verify-social-action", args=[application.id]),
            data="{}",
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token.key}",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], 4315)
        mock_follows.assert_called_once_with("social_user_x", "taskhub_official")

    @patch("taskhub.api_views.user_follows_username_via_apify")
    @patch("taskhub.api_views.apify_twitter_follow_configured")
    @override_settings(TASK_PENDING_APPLICATION_TIMEOUT_MINUTES=5)
    def test_social_action_failed_verify_refreshes_pending_activity(self, mock_configured, mock_follows):
        publisher, applicant, token = self._create_user_pair()
        self._bind_platform_account(
            publisher=publisher,
            applicant=applicant,
            platform=Task.BINDING_TWITTER,
            username="social_user_x",
        )
        mock_configured.return_value = True
        mock_follows.return_value = (False, "并未检测到关注，请先完成关注后再试。")
        task = Task.objects.create(
            publisher=publisher,
            title="关注 Twitter",
            description="打开链接后关注官方账号",
            interaction_type=Task.INTERACTION_FOLLOW,
            binding_platform=Task.BINDING_TWITTER,
            interaction_config={"target_follow_username": "taskhub_official"},
            reward_usdt=Decimal("0.50"),
            reward_th_coin=Decimal("1.00"),
            applicants_limit=5,
            status=Task.STATUS_OPEN,
        )
        application = TaskApplication.objects.create(
            task=task,
            applicant=applicant,
            status=TaskApplication.STATUS_PENDING,
            quoted_price="0.00",
        )
        stale_at = timezone.now() - timedelta(minutes=6)
        TaskApplication.objects.filter(pk=application.pk).update(created_at=stale_at, updated_at=stale_at)

        before = TaskApplication.objects.get(pk=application.pk).updated_at
        response = self.client.post(
            reverse("taskhub-application-verify-social-action", args=[application.id]),
            data="{}",
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token.key}",
        )

        self.assertEqual(response.status_code, 400)
        application.refresh_from_db()
        self.assertEqual(application.status, TaskApplication.STATUS_PENDING)
        self.assertGreater(application.updated_at, before)

    @patch("taskhub.api_views.user_retweeted_tweet_via_apify")
    @patch("taskhub.api_views.apify_twitter_repost_configured")
    def test_twitter_repost_task_verifies_against_bound_account(self, mock_configured, mock_retweeted):
        publisher, applicant, token = self._create_user_pair()
        self._bind_platform_account(
            publisher=publisher,
            applicant=applicant,
            platform=Task.BINDING_TWITTER,
            username="social_user_x",
        )
        mock_configured.return_value = True
        mock_retweeted.return_value = (True, None)
        task = Task.objects.create(
            publisher=publisher,
            title="转发 Twitter",
            description="转发指定推文",
            interaction_type=Task.INTERACTION_REPOST,
            binding_platform=Task.BINDING_TWITTER,
            interaction_config={"target_tweet_url": "https://x.com/taskhub_official/status/1234567890"},
            reward_usdt=Decimal("0.60"),
            reward_th_coin=Decimal("1.20"),
            applicants_limit=5,
            status=Task.STATUS_OPEN,
        )
        application = TaskApplication.objects.create(
            task=task,
            applicant=applicant,
            status=TaskApplication.STATUS_PENDING,
            quoted_price="0.00",
        )

        response = self.client.post(
            reverse("taskhub-application-verify-social-action", args=[application.id]),
            data="{}",
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token.key}",
        )

        self.assertEqual(response.status_code, 200)
        application.refresh_from_db()
        self.assertEqual(application.status, TaskApplication.STATUS_ACCEPTED)
        mock_retweeted.assert_called_once_with("https://x.com/taskhub_official/status/1234567890", "social_user_x")

    @patch("taskhub.api_views.user_reposted_video_via_apify")
    @patch("taskhub.api_views.apify_tiktok_configured")
    def test_tiktok_repost_task_verifies_against_bound_account(self, mock_configured, mock_reposted):
        publisher, applicant, token = self._create_user_pair()
        self._bind_platform_account(
            publisher=publisher,
            applicant=applicant,
            platform=Task.BINDING_TIKTOK,
            username="social_user_tt",
        )
        mock_configured.return_value = True
        mock_reposted.return_value = (True, None)
        task = Task.objects.create(
            publisher=publisher,
            title="转发 TikTok",
            description="转发指定视频",
            interaction_type=Task.INTERACTION_REPOST,
            binding_platform=Task.BINDING_TIKTOK,
            interaction_config={"target_video_url": "https://www.tiktok.com/@taskhub_official/video/1234567890123456789"},
            reward_usdt=Decimal("0.60"),
            reward_th_coin=Decimal("1.20"),
            applicants_limit=5,
            status=Task.STATUS_OPEN,
        )
        application = TaskApplication.objects.create(
            task=task,
            applicant=applicant,
            status=TaskApplication.STATUS_PENDING,
            quoted_price="0.00",
        )

        response = self.client.post(
            reverse("taskhub-application-verify-social-action", args=[application.id]),
            data="{}",
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token.key}",
        )

        self.assertEqual(response.status_code, 200)
        application.refresh_from_db()
        self.assertEqual(application.status, TaskApplication.STATUS_ACCEPTED)
        mock_reposted.assert_called_once_with(
            "social_user_tt",
            "https://www.tiktok.com/@taskhub_official/video/1234567890123456789",
        )

    def test_social_action_verify_completes_pending_follow_task(self):
        publisher, applicant, token = self._create_user_pair()
        self._bind_platform_account(
            publisher=publisher,
            applicant=applicant,
            platform=Task.BINDING_INSTAGRAM,
            username="social_user_ig",
        )
        task = Task.objects.create(
            publisher=publisher,
            title="关注 Instagram",
            description="打开链接后关注官方账号",
            interaction_type=Task.INTERACTION_FOLLOW,
            binding_platform=Task.BINDING_INSTAGRAM,
            interaction_config={"target_profile_url": "https://www.instagram.com/taskhub_official/"},
            reward_usdt=Decimal("0.50"),
            reward_th_coin=Decimal("1.00"),
            applicants_limit=5,
            status=Task.STATUS_OPEN,
        )
        application = TaskApplication.objects.create(
            task=task,
            applicant=applicant,
            status=TaskApplication.STATUS_PENDING,
            quoted_price="0.00",
        )

        response = self.client.post(
            reverse("taskhub-application-verify-social-action", args=[application.id]),
            data="{}",
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token.key}",
        )

        self.assertEqual(response.status_code, 200)
        application.refresh_from_db()
        self.assertEqual(application.status, TaskApplication.STATUS_ACCEPTED)
        payload = response.json()["data"]["application"]
        self.assertEqual(payload["interaction_verify_action"], "verify-social-action")
        self.assertEqual(
            payload["verification_reference_url"],
            "https://www.instagram.com/taskhub_official/",
        )
