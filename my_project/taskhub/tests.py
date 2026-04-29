from unittest.mock import MagicMock, patch

from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.contrib.auth import get_user_model

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

from taskhub.models import ApiToken, MembershipLevelConfig, ReferralRewardConfig, Task, TaskApplication
from taskhub.locale_prefs import normalize_preferred_language, split_start_payload_language
from taskhub.task_rewards import grant_task_completion_reward
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
        self.assertEqual(result["referrer_reward_usdt"], "3.00")
        self.assertTrue(
            Transaction.objects.filter(
                wallet=referrer_wallet,
                change_type="reward",
                asset=Transaction.ASSET_USDT,
                amount="3.00",
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

    def test_recharge_transaction_grants_two_level_commission(self):
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
        ReferralRewardConfig.objects.create(direct_recharge_rate="0.1000", second_recharge_rate="0.0500")
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

        self.assertEqual(str(Wallet.objects.get(user=referrer).balance), "10.00")
        self.assertEqual(str(Wallet.objects.get(user=grandparent).balance), "5.00")


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

    @patch("taskhub.api_views.user_follows_username")
    @patch("taskhub.api_views.get_twitter_bearer_token")
    def test_twitter_follow_task_rejects_when_follow_not_detected(self, mock_bearer, mock_follows):
        publisher, applicant, token = self._create_user_pair()
        self._bind_platform_account(
            publisher=publisher,
            applicant=applicant,
            platform=Task.BINDING_TWITTER,
            username="social_user_x",
        )
        mock_bearer.return_value = "twitter-bearer"
        mock_follows.return_value = False
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
        mock_follows.assert_called_once_with("twitter-bearer", "social_user_x", "taskhub_official")

    @patch("taskhub.api_views.user_retweeted_tweet")
    @patch("taskhub.api_views.get_twitter_bearer_token")
    def test_twitter_repost_task_verifies_against_bound_account(self, mock_bearer, mock_retweeted):
        publisher, applicant, token = self._create_user_pair()
        self._bind_platform_account(
            publisher=publisher,
            applicant=applicant,
            platform=Task.BINDING_TWITTER,
            username="social_user_x",
        )
        mock_bearer.return_value = "twitter-bearer"
        mock_retweeted.return_value = True
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
        mock_retweeted.assert_called_once_with("twitter-bearer", "1234567890", "social_user_x")

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
