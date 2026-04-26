from django.db import migrations


def repair_auto_recharge_schema(apps, schema_editor):
    connection = schema_editor.connection
    if connection.vendor != "mysql":
        return

    def exists(query, params):
        with connection.cursor() as cursor:
            cursor.execute(query, params)
            return cursor.fetchone() is not None

    def has_table(name):
        return exists(
            "SELECT 1 FROM information_schema.TABLES "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s",
            [name],
        )

    def has_column(table_name, column_name):
        return exists(
            "SELECT 1 FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s AND COLUMN_NAME = %s",
            [table_name, column_name],
        )

    def has_index(table_name, index_name):
        return exists(
            "SELECT 1 FROM information_schema.STATISTICS "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s AND INDEX_NAME = %s",
            [table_name, index_name],
        )

    def has_constraint(table_name, constraint_name):
        return exists(
            "SELECT 1 FROM information_schema.TABLE_CONSTRAINTS "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s AND CONSTRAINT_NAME = %s",
            [table_name, constraint_name],
        )

    def has_fk_on_column(table_name, column_name):
        return exists(
            "SELECT 1 FROM information_schema.KEY_COLUMN_USAGE "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s "
            "AND COLUMN_NAME = %s AND REFERENCED_TABLE_NAME IS NOT NULL",
            [table_name, column_name],
        )

    def run(sql):
        with connection.cursor() as cursor:
            cursor.execute(sql)

    def add_column(table_name, column_name, sql, after_sql=None):
        if has_column(table_name, column_name):
            return
        run(sql)
        if after_sql:
            run(after_sql)

    if has_table("wallet_recharge_network_config"):
        add_column(
            "wallet_recharge_network_config",
            "token_contract_address",
            "ALTER TABLE `wallet_recharge_network_config` "
            "ADD COLUMN `token_contract_address` varchar(160) NOT NULL DEFAULT ''",
        )
        add_column(
            "wallet_recharge_network_config",
            "rpc_endpoint",
            "ALTER TABLE `wallet_recharge_network_config` "
            "ADD COLUMN `rpc_endpoint` varchar(255) NOT NULL DEFAULT ''",
        )
        add_column(
            "wallet_recharge_network_config",
            "api_key",
            "ALTER TABLE `wallet_recharge_network_config` ADD COLUMN `api_key` longtext NULL",
            "UPDATE `wallet_recharge_network_config` SET `api_key` = '' WHERE `api_key` IS NULL",
        )
        add_column(
            "wallet_recharge_network_config",
            "master_mnemonic",
            "ALTER TABLE `wallet_recharge_network_config` ADD COLUMN `master_mnemonic` longtext NULL",
            "UPDATE `wallet_recharge_network_config` SET `master_mnemonic` = '' WHERE `master_mnemonic` IS NULL",
        )
        add_column(
            "wallet_recharge_network_config",
            "mnemonic_passphrase",
            "ALTER TABLE `wallet_recharge_network_config` "
            "ADD COLUMN `mnemonic_passphrase` varchar(255) NOT NULL DEFAULT ''",
        )
        add_column(
            "wallet_recharge_network_config",
            "collector_address",
            "ALTER TABLE `wallet_recharge_network_config` "
            "ADD COLUMN `collector_address` varchar(160) NOT NULL DEFAULT ''",
        )
        add_column(
            "wallet_recharge_network_config",
            "collector_private_key",
            "ALTER TABLE `wallet_recharge_network_config` ADD COLUMN `collector_private_key` longtext NULL",
            "UPDATE `wallet_recharge_network_config` "
            "SET `collector_private_key` = '' WHERE `collector_private_key` IS NULL",
        )
        add_column(
            "wallet_recharge_network_config",
            "token_decimals",
            "ALTER TABLE `wallet_recharge_network_config` "
            "ADD COLUMN `token_decimals` smallint unsigned NOT NULL DEFAULT 6",
        )
        add_column(
            "wallet_recharge_network_config",
            "evm_chain_id",
            "ALTER TABLE `wallet_recharge_network_config` "
            "ADD COLUMN `evm_chain_id` bigint unsigned NULL",
        )
        add_column(
            "wallet_recharge_network_config",
            "next_derivation_index",
            "ALTER TABLE `wallet_recharge_network_config` "
            "ADD COLUMN `next_derivation_index` int unsigned NOT NULL DEFAULT 0",
        )
        add_column(
            "wallet_recharge_network_config",
            "scan_from_block",
            "ALTER TABLE `wallet_recharge_network_config` "
            "ADD COLUMN `scan_from_block` bigint NULL",
        )
        add_column(
            "wallet_recharge_network_config",
            "sweep_enabled",
            "ALTER TABLE `wallet_recharge_network_config` "
            "ADD COLUMN `sweep_enabled` bool NOT NULL DEFAULT 1",
        )
        add_column(
            "wallet_recharge_network_config",
            "min_sweep_amount_usdt",
            "ALTER TABLE `wallet_recharge_network_config` "
            "ADD COLUMN `min_sweep_amount_usdt` decimal(20,2) NOT NULL DEFAULT 1.00",
        )
        add_column(
            "wallet_recharge_network_config",
            "topup_native_amount",
            "ALTER TABLE `wallet_recharge_network_config` "
            "ADD COLUMN `topup_native_amount` decimal(20,8) NOT NULL DEFAULT 0.00030000",
        )
        add_column(
            "wallet_recharge_network_config",
            "token_transfer_gas_limit",
            "ALTER TABLE `wallet_recharge_network_config` "
            "ADD COLUMN `token_transfer_gas_limit` int unsigned NOT NULL DEFAULT 100000",
        )
        add_column(
            "wallet_recharge_network_config",
            "tron_fee_limit_sun",
            "ALTER TABLE `wallet_recharge_network_config` "
            "ADD COLUMN `tron_fee_limit_sun` bigint unsigned NOT NULL DEFAULT 30000000",
        )

    if has_table("wallet_recharge_request"):
        if has_index("wallet_recharge_request", "uniq_recharge_chain_tx_hash"):
            run("ALTER TABLE `wallet_recharge_request` DROP INDEX `uniq_recharge_chain_tx_hash`")
        add_column(
            "wallet_recharge_request",
            "block_number",
            "ALTER TABLE `wallet_recharge_request` ADD COLUMN `block_number` bigint NULL",
        )
        add_column(
            "wallet_recharge_request",
            "confirmations",
            "ALTER TABLE `wallet_recharge_request` "
            "ADD COLUMN `confirmations` int unsigned NOT NULL DEFAULT 0",
        )
        add_column(
            "wallet_recharge_request",
            "credited_at",
            "ALTER TABLE `wallet_recharge_request` ADD COLUMN `credited_at` datetime(6) NULL",
        )
        add_column(
            "wallet_recharge_request",
            "last_error",
            "ALTER TABLE `wallet_recharge_request` "
            "ADD COLUMN `last_error` varchar(255) NOT NULL DEFAULT ''",
        )
        add_column(
            "wallet_recharge_request",
            "log_index",
            "ALTER TABLE `wallet_recharge_request` "
            "ADD COLUMN `log_index` int unsigned NOT NULL DEFAULT 0",
        )
        add_column(
            "wallet_recharge_request",
            "network_id",
            "ALTER TABLE `wallet_recharge_request` ADD COLUMN `network_id` bigint NULL",
        )
        add_column(
            "wallet_recharge_request",
            "raw_payload",
            "ALTER TABLE `wallet_recharge_request` ADD COLUMN `raw_payload` json NULL",
            "UPDATE `wallet_recharge_request` SET `raw_payload` = JSON_OBJECT() "
            "WHERE `raw_payload` IS NULL",
        )
        add_column(
            "wallet_recharge_request",
            "source_type",
            "ALTER TABLE `wallet_recharge_request` "
            "ADD COLUMN `source_type` varchar(20) NOT NULL DEFAULT 'manual_submission'",
        )
        add_column(
            "wallet_recharge_request",
            "sweep_status",
            "ALTER TABLE `wallet_recharge_request` "
            "ADD COLUMN `sweep_status` varchar(20) NOT NULL DEFAULT 'none'",
        )
        add_column(
            "wallet_recharge_request",
            "sweep_tx_hash",
            "ALTER TABLE `wallet_recharge_request` "
            "ADD COLUMN `sweep_tx_hash` varchar(160) NOT NULL DEFAULT ''",
        )
        add_column(
            "wallet_recharge_request",
            "swept_at",
            "ALTER TABLE `wallet_recharge_request` ADD COLUMN `swept_at` datetime(6) NULL",
        )
        add_column(
            "wallet_recharge_request",
            "token_contract_address",
            "ALTER TABLE `wallet_recharge_request` "
            "ADD COLUMN `token_contract_address` varchar(160) NOT NULL DEFAULT ''",
        )
        add_column(
            "wallet_recharge_request",
            "user_address_id",
            "ALTER TABLE `wallet_recharge_request` ADD COLUMN `user_address_id` bigint NULL",
        )

    if not has_table("wallet_user_recharge_address"):
        run(
            "CREATE TABLE `wallet_user_recharge_address` ("
            "`id` bigint AUTO_INCREMENT NOT NULL PRIMARY KEY, "
            "`user_id` bigint NOT NULL, "
            "`network_id` bigint NOT NULL, "
            "`address` varchar(160) NOT NULL UNIQUE, "
            "`address_hex` varchar(128) NOT NULL DEFAULT '', "
            "`derivation_index` int unsigned NOT NULL, "
            "`account_path` varchar(128) NOT NULL, "
            "`status` varchar(16) NOT NULL DEFAULT 'active', "
            "`last_seen_at` datetime(6) NULL, "
            "`last_swept_at` datetime(6) NULL, "
            "`created_at` datetime(6) NOT NULL, "
            "`updated_at` datetime(6) NOT NULL, "
            "CONSTRAINT `uniq_user_recharge_address` UNIQUE (`user_id`, `network_id`), "
            "CONSTRAINT `uniq_network_derivation_index` UNIQUE (`network_id`, `derivation_index`), "
            "CONSTRAINT `fk_wallet_user_addr_user` FOREIGN KEY (`user_id`) REFERENCES `frontend_user`(`id`), "
            "CONSTRAINT `fk_wallet_user_addr_network` FOREIGN KEY (`network_id`) REFERENCES `wallet_recharge_network_config`(`id`)"
            ") ENGINE=InnoDB"
        )
    elif has_table("wallet_user_recharge_address"):
        add_column(
            "wallet_user_recharge_address",
            "user_id",
            "ALTER TABLE `wallet_user_recharge_address` ADD COLUMN `user_id` bigint NOT NULL",
        )
        add_column(
            "wallet_user_recharge_address",
            "network_id",
            "ALTER TABLE `wallet_user_recharge_address` ADD COLUMN `network_id` bigint NOT NULL",
        )
        add_column(
            "wallet_user_recharge_address",
            "address",
            "ALTER TABLE `wallet_user_recharge_address` "
            "ADD COLUMN `address` varchar(160) NOT NULL UNIQUE",
        )
        add_column(
            "wallet_user_recharge_address",
            "address_hex",
            "ALTER TABLE `wallet_user_recharge_address` "
            "ADD COLUMN `address_hex` varchar(128) NOT NULL DEFAULT ''",
        )
        add_column(
            "wallet_user_recharge_address",
            "derivation_index",
            "ALTER TABLE `wallet_user_recharge_address` "
            "ADD COLUMN `derivation_index` int unsigned NOT NULL",
        )
        add_column(
            "wallet_user_recharge_address",
            "account_path",
            "ALTER TABLE `wallet_user_recharge_address` "
            "ADD COLUMN `account_path` varchar(128) NOT NULL DEFAULT ''",
        )
        add_column(
            "wallet_user_recharge_address",
            "status",
            "ALTER TABLE `wallet_user_recharge_address` "
            "ADD COLUMN `status` varchar(16) NOT NULL DEFAULT 'active'",
        )
        add_column(
            "wallet_user_recharge_address",
            "last_seen_at",
            "ALTER TABLE `wallet_user_recharge_address` ADD COLUMN `last_seen_at` datetime(6) NULL",
        )
        add_column(
            "wallet_user_recharge_address",
            "last_swept_at",
            "ALTER TABLE `wallet_user_recharge_address` ADD COLUMN `last_swept_at` datetime(6) NULL",
        )
        add_column(
            "wallet_user_recharge_address",
            "created_at",
            "ALTER TABLE `wallet_user_recharge_address` "
            "ADD COLUMN `created_at` datetime(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)",
        )
        add_column(
            "wallet_user_recharge_address",
            "updated_at",
            "ALTER TABLE `wallet_user_recharge_address` "
            "ADD COLUMN `updated_at` datetime(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) "
            "ON UPDATE CURRENT_TIMESTAMP(6)",
        )

    if has_table("wallet_user_recharge_address"):
        if not has_constraint("wallet_user_recharge_address", "uniq_user_recharge_address"):
            run(
                "ALTER TABLE `wallet_user_recharge_address` "
                "ADD CONSTRAINT `uniq_user_recharge_address` UNIQUE (`user_id`, `network_id`)"
            )
        if not has_constraint("wallet_user_recharge_address", "uniq_network_derivation_index"):
            run(
                "ALTER TABLE `wallet_user_recharge_address` "
                "ADD CONSTRAINT `uniq_network_derivation_index` UNIQUE (`network_id`, `derivation_index`)"
            )
        if not has_fk_on_column("wallet_user_recharge_address", "user_id"):
            run(
                "ALTER TABLE `wallet_user_recharge_address` "
                "ADD CONSTRAINT `fk_wallet_user_addr_user` "
                "FOREIGN KEY (`user_id`) REFERENCES `frontend_user`(`id`)"
            )
        if not has_fk_on_column("wallet_user_recharge_address", "network_id"):
            run(
                "ALTER TABLE `wallet_user_recharge_address` "
                "ADD CONSTRAINT `fk_wallet_user_addr_network` "
                "FOREIGN KEY (`network_id`) REFERENCES `wallet_recharge_network_config`(`id`)"
            )

    if has_table("wallet_recharge_request"):
        if has_column("wallet_recharge_request", "network_id") and not has_fk_on_column(
            "wallet_recharge_request", "network_id"
        ):
            run(
                "ALTER TABLE `wallet_recharge_request` "
                "ADD CONSTRAINT `fk_recharge_request_network` "
                "FOREIGN KEY (`network_id`) REFERENCES `wallet_recharge_network_config`(`id`)"
            )
        if has_column("wallet_recharge_request", "user_address_id") and not has_fk_on_column(
            "wallet_recharge_request", "user_address_id"
        ):
            run(
                "ALTER TABLE `wallet_recharge_request` "
                "ADD CONSTRAINT `fk_recharge_request_user_address` "
                "FOREIGN KEY (`user_address_id`) REFERENCES `wallet_user_recharge_address`(`id`)"
            )
        if not has_constraint("wallet_recharge_request", "uniq_recharge_chain_tx_hash_log"):
            run(
                "ALTER TABLE `wallet_recharge_request` "
                "ADD CONSTRAINT `uniq_recharge_chain_tx_hash_log` "
                "UNIQUE (`chain`, `tx_hash`, `log_index`)"
            )


class Migration(migrations.Migration):
    dependencies = [
        ("wallets", "0010_userrechargeaddress_and_more"),
    ]

    operations = [
        migrations.RunPython(repair_auto_recharge_schema, migrations.RunPython.noop),
    ]
