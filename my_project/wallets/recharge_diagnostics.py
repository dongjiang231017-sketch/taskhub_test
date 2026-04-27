from __future__ import annotations

from dataclasses import dataclass

from eth_account import Account
from web3 import Web3

from .auto_recharge import (
    EvmUsdtClient,
    TronUsdtClient,
    _derive_account,
    _tron_base58_from_private_key,
    _tron_base58_to_hex,
)
from .models import RechargeNetworkConfig


@dataclass(slots=True)
class RechargeDiagnosticCheck:
    label: str
    ok: bool
    detail: str


@dataclass(slots=True)
class RechargeDiagnosticResult:
    checks: list[RechargeDiagnosticCheck]

    @property
    def ok(self) -> bool:
        return all(check.ok for check in self.checks)


def _normalize_tron_address(address: str) -> str:
    return (address or "").strip()


def _normalize_evm_address(address: str) -> str:
    s = (address or "").strip()
    if not s or not Web3.is_address(s):
        return ""
    return Web3.to_checksum_address(s)


def _check_required_fields(network: RechargeNetworkConfig) -> RechargeDiagnosticCheck:
    required = (
        ("token_contract_address", "USDT 合约地址"),
        ("rpc_endpoint", "RPC / API 地址"),
        ("master_mnemonic", "HD 主助记词"),
        ("collector_address", "归集地址"),
        ("collector_private_key", "归集/手续费私钥"),
    )
    missing = [label for field, label in required if not str(getattr(network, field, "") or "").strip()]
    if missing:
        return RechargeDiagnosticCheck("必填项", False, f"缺少：{', '.join(missing)}")
    return RechargeDiagnosticCheck("必填项", True, "已完整填写")


def _check_token_contract(network: RechargeNetworkConfig) -> RechargeDiagnosticCheck:
    value = (network.token_contract_address or "").strip()
    if not value:
        return RechargeDiagnosticCheck("USDT 合约", False, "未填写")
    try:
        if network.is_tron:
            _tron_base58_to_hex(value)
        else:
            if not Web3.is_address(value):
                raise ValueError("invalid evm address")
        return RechargeDiagnosticCheck("USDT 合约", True, "格式有效")
    except Exception as exc:  # pragma: no cover - defensive diagnostics
        return RechargeDiagnosticCheck("USDT 合约", False, f"格式无效：{exc.__class__.__name__}")


def _check_mnemonic(network: RechargeNetworkConfig) -> RechargeDiagnosticCheck:
    if not (network.master_mnemonic or "").strip():
        return RechargeDiagnosticCheck("助记词派生", False, "未填写")
    try:
        material = _derive_account(network, int(network.next_derivation_index or 0))
        if network.is_tron and not material.address.startswith("T"):
            raise ValueError("derived tron address malformed")
        if network.is_evm and not Web3.is_address(material.address):
            raise ValueError("derived evm address malformed")
        return RechargeDiagnosticCheck("助记词派生", True, f"可正常派生地址（序号 {material.derivation_index}）")
    except Exception as exc:
        return RechargeDiagnosticCheck("助记词派生", False, f"派生失败：{exc.__class__.__name__}")


def _check_collector_private_key(network: RechargeNetworkConfig) -> RechargeDiagnosticCheck:
    value = (network.collector_private_key or "").strip()
    if not value:
        return RechargeDiagnosticCheck("归集私钥", False, "未填写")
    try:
        Account.from_key(value)
        return RechargeDiagnosticCheck("归集私钥", True, "格式有效")
    except Exception as exc:
        return RechargeDiagnosticCheck("归集私钥", False, f"格式无效：{exc.__class__.__name__}")


def _check_collector_address(network: RechargeNetworkConfig) -> RechargeDiagnosticCheck:
    value = (network.collector_address or "").strip()
    if not value:
        return RechargeDiagnosticCheck("归集地址", False, "未填写")
    try:
        if network.is_tron:
            _tron_base58_to_hex(value)
        else:
            if not Web3.is_address(value):
                raise ValueError("invalid evm address")
        return RechargeDiagnosticCheck("归集地址", True, "格式有效")
    except Exception as exc:
        return RechargeDiagnosticCheck("归集地址", False, f"格式无效：{exc.__class__.__name__}")


def _check_collector_match(network: RechargeNetworkConfig) -> RechargeDiagnosticCheck:
    address = (network.collector_address or "").strip()
    private_key = (network.collector_private_key or "").strip()
    if not address or not private_key:
        return RechargeDiagnosticCheck("地址私钥匹配", False, "归集地址或私钥未填写")
    try:
        owner = Account.from_key(private_key)
        if network.is_tron:
            derived_address, _ = _tron_base58_from_private_key(owner.key.hex())
            ok = _normalize_tron_address(derived_address) == _normalize_tron_address(address)
        else:
            derived_address = Web3.to_checksum_address(owner.address)
            ok = _normalize_evm_address(derived_address) == _normalize_evm_address(address)
        if ok:
            return RechargeDiagnosticCheck("地址私钥匹配", True, "私钥与归集地址一致")
        return RechargeDiagnosticCheck("地址私钥匹配", False, "私钥与归集地址不一致")
    except Exception as exc:
        return RechargeDiagnosticCheck("地址私钥匹配", False, f"校验失败：{exc.__class__.__name__}")


def _check_live_rpc(network: RechargeNetworkConfig) -> RechargeDiagnosticCheck:
    if not (network.rpc_endpoint or "").strip():
        return RechargeDiagnosticCheck("RPC 连通", False, "未填写 RPC / API 地址")
    try:
        if network.is_tron:
            latest_block = TronUsdtClient(network).latest_block()
        else:
            latest_block = EvmUsdtClient(network).latest_block()
        if int(latest_block) <= 0:
            return RechargeDiagnosticCheck("RPC 连通", False, "已连接但区块高度异常")
        return RechargeDiagnosticCheck("RPC 连通", True, f"最新区块：{latest_block}")
    except Exception as exc:
        return RechargeDiagnosticCheck("RPC 连通", False, f"请求失败：{exc.__class__.__name__}")


def diagnose_recharge_network(network: RechargeNetworkConfig, *, live_check: bool = False) -> RechargeDiagnosticResult:
    checks = [
        _check_required_fields(network),
        _check_token_contract(network),
        _check_mnemonic(network),
        _check_collector_address(network),
        _check_collector_private_key(network),
        _check_collector_match(network),
    ]
    if live_check:
        checks.append(_check_live_rpc(network))
    return RechargeDiagnosticResult(checks=checks)
