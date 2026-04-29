from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP
from typing import Iterable

import base58
import requests
from django.db import transaction
from django.utils import timezone
from eth_abi import encode
from eth_account import Account
from eth_keys import keys as eth_keys
from eth_utils import keccak
from web3 import Web3

from users.models import FrontendUser

from .models import RechargeNetworkConfig, RechargeRequest, UserRechargeAddress

Account.enable_unaudited_hdwallet_features()

_MONEY_QUANT = Decimal("0.01")
_EVM_TRANSFER_TOPIC = "0x" + Web3.keccak(text="Transfer(address,address,uint256)").hex()
_ERC20_ABI = [
    {
        "constant": True,
        "inputs": [{"name": "owner", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "constant": False,
        "inputs": [
            {"name": "to", "type": "address"},
            {"name": "value", "type": "uint256"},
        ],
        "name": "transfer",
        "outputs": [{"name": "", "type": "bool"}],
        "stateMutability": "nonpayable",
        "type": "function",
    },
]


@dataclass(slots=True)
class DerivedAccount:
    address: str
    address_hex: str
    private_key_hex: str
    account_path: str
    derivation_index: int


@dataclass(slots=True)
class DetectedTransfer:
    tx_hash: str
    log_index: int
    from_address: str
    to_address: str
    amount: Decimal
    block_number: int | None
    confirmations: int
    raw_payload: dict


def _normalize_amount(raw_units: int, decimals: int) -> Decimal:
    scale = Decimal(10) ** int(decimals or 6)
    return (Decimal(raw_units) / scale).quantize(_MONEY_QUANT, rounding=ROUND_HALF_UP)


def _to_token_units(amount: Decimal, decimals: int) -> int:
    scale = Decimal(10) ** int(decimals or 6)
    return int((Decimal(str(amount)) * scale).quantize(Decimal("1"), rounding=ROUND_DOWN))


def _normalize_mnemonic(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _normalize_private_key_hex(value: str) -> str:
    cleaned = re.sub(r"\s+", "", str(value or "")).strip()
    if cleaned.lower().startswith("0x"):
        cleaned = cleaned[2:]
    return cleaned


def _tron_hex_to_base58(address_hex: str) -> str:
    payload = bytes.fromhex(address_hex)
    if len(payload) != 21 or payload[0] != 0x41:
        raise ValueError("invalid tron hex address")
    checksum = hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4]
    return base58.b58encode(payload + checksum).decode()


def _normalize_tron_address(address: str) -> str:
    cleaned = re.sub(r"\s+", "", str(address or "")).strip()
    lowered = cleaned.lower()
    if lowered.startswith("0x"):
        cleaned = cleaned[2:]
    if len(cleaned) == 42 and re.fullmatch(r"[0-9a-fA-F]{42}", cleaned) and cleaned[:2].lower() == "41":
        return _tron_hex_to_base58(cleaned)
    return cleaned


def _tron_base58_from_private_key(private_key_hex: str) -> tuple[str, str]:
    key = eth_keys.PrivateKey(bytes.fromhex(_normalize_private_key_hex(private_key_hex)))
    payload = b"\x41" + keccak(key.public_key.to_bytes())[-20:]
    checksum = hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4]
    return base58.b58encode(payload + checksum).decode(), payload.hex()


def _tron_base58_to_hex(address: str) -> str:
    address = _normalize_tron_address(address)
    raw = base58.b58decode(address)
    if len(raw) != 25:
        raise ValueError("invalid tron address length")
    payload, checksum = raw[:-4], raw[-4:]
    expected = hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4]
    if checksum != expected:
        raise ValueError("invalid tron address checksum")
    return payload.hex()


def _derive_account(network: RechargeNetworkConfig, index: int) -> DerivedAccount:
    account_path = network.build_account_path(index)
    acct = Account.from_mnemonic(
        _normalize_mnemonic(network.master_mnemonic),
        passphrase=(network.mnemonic_passphrase or "").strip(),
        account_path=account_path,
    )
    private_key_hex = acct.key.hex()
    if network.is_tron:
        address, address_hex = _tron_base58_from_private_key(private_key_hex)
    else:
        address = Web3.to_checksum_address(acct.address)
        address_hex = address
    return DerivedAccount(
        address=address,
        address_hex=address_hex,
        private_key_hex=private_key_hex,
        account_path=account_path,
        derivation_index=int(index),
    )


def ensure_user_recharge_address(user: FrontendUser, network: RechargeNetworkConfig) -> UserRechargeAddress | None:
    existing = UserRechargeAddress.objects.filter(user=user, network=network).first()
    if existing is not None:
        return existing
    if not _normalize_mnemonic(network.master_mnemonic):
        return None
    with transaction.atomic():
        network = RechargeNetworkConfig.objects.select_for_update().get(pk=network.pk)
        existing = UserRechargeAddress.objects.filter(user=user, network=network).first()
        if existing is not None:
            return existing
        material = _derive_account(network, network.next_derivation_index)
        row = UserRechargeAddress.objects.create(
            user=user,
            network=network,
            address=material.address,
            address_hex=material.address_hex,
            derivation_index=material.derivation_index,
            account_path=material.account_path,
        )
        network.next_derivation_index += 1
        network.save(update_fields=["next_derivation_index", "updated_at"])
        return row


def ensure_user_addresses_for_active_networks(user: FrontendUser) -> list[UserRechargeAddress]:
    rows: list[UserRechargeAddress] = []
    for network in RechargeNetworkConfig.objects.filter(is_active=True).order_by("sort_order", "id"):
        row = ensure_user_recharge_address(user, network)
        if row is not None:
            rows.append(row)
    return rows


class EvmUsdtClient:
    def __init__(self, network: RechargeNetworkConfig):
        self.network = network
        self.w3 = Web3(Web3.HTTPProvider((network.rpc_endpoint or "").strip(), request_kwargs={"timeout": 30}))
        self.contract = self.w3.eth.contract(
            address=Web3.to_checksum_address((network.token_contract_address or "").strip()),
            abi=_ERC20_ABI,
        )

    def latest_block(self) -> int:
        return int(self.w3.eth.block_number)

    def stable_scan_to_block(self, *, from_block: int, requested_to_block: int, safety_margin: int = 6) -> int:
        """
        Public RPCs behind load balancers may return a slightly newer head for
        blockNumber than the backend that later serves eth_getLogs. Stay a few
        blocks behind to avoid "beyond current head block" false negatives.
        """
        latest_visible = self.latest_block()
        safe_to = min(int(requested_to_block), max(0, int(latest_visible) - max(0, int(safety_margin))))
        if safe_to < int(from_block):
            return int(from_block)
        return int(safe_to)

    def probe_log_scanning(self) -> int:
        latest = self.latest_block()
        to_block = self.stable_scan_to_block(from_block=max(1, latest - 1), requested_to_block=latest)
        from_block = max(1, to_block - 1)
        self.w3.eth.get_logs(
            {
                "address": Web3.to_checksum_address((self.network.token_contract_address or "").strip()),
                "fromBlock": int(from_block),
                "toBlock": int(to_block),
                "topics": [_EVM_TRANSFER_TOPIC],
            }
        )
        return to_block

    def list_new_transfers(
        self,
        address_rows: Iterable[UserRechargeAddress],
        *,
        from_block: int,
        to_block: int,
    ) -> list[DetectedTransfer]:
        address_map = {Web3.to_checksum_address(row.address): row for row in address_rows if row.address}
        if not address_map:
            return []
        rows = list(address_map.values())
        out: list[DetectedTransfer] = []
        for start in range(0, len(rows), 50):
            chunk = rows[start : start + 50]
            topics = ["0x" + ("0" * 24) + row.address[2:].lower() for row in chunk]
            logs = self.w3.eth.get_logs(
                {
                    "address": Web3.to_checksum_address((self.network.token_contract_address or "").strip()),
                    "fromBlock": int(from_block),
                    "toBlock": int(to_block),
                    "topics": [_EVM_TRANSFER_TOPIC, None, topics],
                }
            )
            latest = self.latest_block()
            for log in logs:
                to_address = Web3.to_checksum_address("0x" + log["topics"][2].hex()[-40:])
                from_address = Web3.to_checksum_address("0x" + log["topics"][1].hex()[-40:])
                value_int = int(log["data"].hex(), 16)
                out.append(
                    DetectedTransfer(
                        tx_hash=log["transactionHash"].hex(),
                        log_index=int(log["logIndex"]),
                        from_address=from_address,
                        to_address=to_address,
                        amount=_normalize_amount(value_int, self.network.token_decimals),
                        block_number=int(log["blockNumber"]),
                        confirmations=max(0, latest - int(log["blockNumber"]) + 1),
                        raw_payload={
                            "topics": [topic.hex() for topic in log["topics"]],
                            "data": log["data"].hex(),
                        },
                    )
                )
        return out

    def token_balance(self, address: str) -> Decimal:
        raw = int(self.contract.functions.balanceOf(Web3.to_checksum_address(address)).call())
        return _normalize_amount(raw, self.network.token_decimals)

    def native_balance(self, address: str) -> Decimal:
        raw = int(self.w3.eth.get_balance(Web3.to_checksum_address(address)))
        return Decimal(raw) / (Decimal(10) ** 18)

    def confirm_sweep_receipt(self, tx_hash: str) -> bool | None:
        try:
            receipt = self.w3.eth.get_transaction_receipt(tx_hash)
        except Exception:
            return None
        return bool(getattr(receipt, "status", receipt.get("status", 0)) == 1)

    def send_native_topup(self, *, to_address: str, amount: Decimal) -> str:
        gas_payer = Account.from_key(_normalize_private_key_hex(self.network.collector_private_key))
        gas_price = int(self.w3.eth.gas_price)
        value_wei = int((Decimal(str(amount)) * (Decimal(10) ** 18)).quantize(Decimal("1"), rounding=ROUND_DOWN))
        tx = {
            "chainId": int(self.network.evm_chain_id or self.w3.eth.chain_id),
            "nonce": self.w3.eth.get_transaction_count(gas_payer.address),
            "to": Web3.to_checksum_address(to_address),
            "value": value_wei,
            "gas": 21000,
            "gasPrice": gas_price,
        }
        signed = gas_payer.sign_transaction(tx)
        return self.w3.eth.send_raw_transaction(signed.raw_transaction).hex()

    def send_token_sweep(self, *, from_private_key: str, from_address: str) -> str:
        balance = self.contract.functions.balanceOf(Web3.to_checksum_address(from_address)).call()
        if int(balance) <= 0:
            raise ValueError("no token balance")
        sender = Account.from_key(_normalize_private_key_hex(from_private_key))
        gas_price = int(self.w3.eth.gas_price)
        tx = self.contract.functions.transfer(
            Web3.to_checksum_address((self.network.collector_address or "").strip()),
            int(balance),
        ).build_transaction(
            {
                "chainId": int(self.network.evm_chain_id or self.w3.eth.chain_id),
                "from": Web3.to_checksum_address(from_address),
                "nonce": self.w3.eth.get_transaction_count(Web3.to_checksum_address(from_address)),
                "gas": int(self.network.token_transfer_gas_limit or 100000),
                "gasPrice": gas_price,
                "value": 0,
            }
        )
        signed = sender.sign_transaction(tx)
        return self.w3.eth.send_raw_transaction(signed.raw_transaction).hex()


class TronUsdtClient:
    def __init__(self, network: RechargeNetworkConfig):
        self.network = network
        self.base_url = (network.rpc_endpoint or "").strip().rstrip("/")
        self.session = requests.Session()
        api_key = (network.api_key or "").strip()
        if api_key:
            self.session.headers.update({"TRON-PRO-API-KEY": api_key})

    def _get(self, path: str, **params) -> dict:
        resp = self.session.get(f"{self.base_url}{path}", params=params, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def _post(self, path: str, payload: dict) -> dict:
        resp = self.session.post(f"{self.base_url}{path}", json=payload, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def latest_block(self) -> int:
        data = self._post("/wallet/getnowblock", {})
        return int(data.get("block_header", {}).get("raw_data", {}).get("number", 0))

    def trc20_transfers_for_address(self, address: str) -> list[dict]:
        data = self._get(
            f"/v1/accounts/{address}/transactions/trc20",
            only_to="true",
            limit=200,
            contract_address=(self.network.token_contract_address or "").strip(),
            order_by="block_timestamp,asc",
        )
        return list(data.get("data") or [])

    def get_transaction_info(self, tx_hash: str) -> dict:
        return self._post("/wallet/gettransactioninfobyid", {"value": tx_hash})

    def token_balance(self, address: str) -> Decimal:
        owner_hex = _tron_base58_to_hex(address)
        contract_hex = _tron_base58_to_hex((self.network.token_contract_address or "").strip())
        encoded = encode(["address"], ["0x" + owner_hex[2:]]).hex()
        data = self._post(
            "/wallet/triggerconstantcontract",
            {
                "owner_address": owner_hex,
                "contract_address": contract_hex,
                "function_selector": "balanceOf(address)",
                "parameter": encoded,
                "visible": False,
            },
        )
        raw = int((data.get("constant_result") or ["0"])[0], 16)
        return _normalize_amount(raw, self.network.token_decimals)

    def native_balance(self, address: str) -> Decimal:
        owner_hex = _tron_base58_to_hex(address)
        data = self._post("/wallet/getaccount", {"address": owner_hex, "visible": False})
        raw = int(data.get("balance") or 0)
        return Decimal(raw) / Decimal(1_000_000)

    def confirm_sweep_receipt(self, tx_hash: str) -> bool | None:
        info = self.get_transaction_info(tx_hash)
        if not info:
            return None
        receipt = info.get("receipt") or {}
        if receipt.get("result") == "SUCCESS":
            return True
        if receipt.get("result"):
            return False
        return None

    def _sign_tx(self, tx: dict, private_key_hex: str) -> dict:
        digest = hashlib.sha256(bytes.fromhex(tx["raw_data_hex"])).digest()
        key = eth_keys.PrivateKey(bytes.fromhex(private_key_hex))
        signature = key.sign_msg_hash(digest).to_bytes().hex()
        signed = dict(tx)
        signed["signature"] = [signature]
        return signed

    def _broadcast(self, tx: dict) -> str:
        data = self._post("/wallet/broadcasttransaction", tx)
        if not data.get("result"):
            raise ValueError(data.get("message") or data)
        return str(tx.get("txID") or data.get("txid") or "")

    def send_native_topup(self, *, to_address: str, amount: Decimal) -> str:
        owner = Account.from_key(_normalize_private_key_hex(self.network.collector_private_key))
        owner_address, owner_hex = _tron_base58_from_private_key(owner.key.hex())
        tx = self._post(
            "/wallet/createtransaction",
            {
                "owner_address": owner_hex,
                "to_address": _tron_base58_to_hex(to_address),
                "amount": int((Decimal(str(amount)) * Decimal(1_000_000)).quantize(Decimal("1"), rounding=ROUND_DOWN)),
                "visible": False,
            },
        )
        return self._broadcast(self._sign_tx(tx, owner.key.hex()))

    def send_token_sweep(self, *, from_private_key: str, from_address: str) -> str:
        owner_hex = _tron_base58_to_hex(from_address)
        contract_hex = _tron_base58_to_hex((self.network.token_contract_address or "").strip())
        collector_hex = _tron_base58_to_hex((self.network.collector_address or "").strip())
        balance = self.token_balance(from_address)
        raw_balance = _to_token_units(balance, self.network.token_decimals)
        if raw_balance <= 0:
            raise ValueError("no token balance")
        parameter = encode(["address", "uint256"], ["0x" + collector_hex[2:], raw_balance]).hex()
        tx = self._post(
            "/wallet/triggersmartcontract",
            {
                "owner_address": owner_hex,
                "contract_address": contract_hex,
                "function_selector": "transfer(address,uint256)",
                "parameter": parameter,
                "fee_limit": int(self.network.tron_fee_limit_sun or 30000000),
                "call_value": 0,
                "visible": False,
            },
        ).get("transaction") or {}
        if not tx:
            raise ValueError("empty tron smart contract transaction")
        return self._broadcast(self._sign_tx(tx, from_private_key))


def _upsert_detected_transfer(network: RechargeNetworkConfig, address_row: UserRechargeAddress, item: DetectedTransfer) -> RechargeRequest:
    req, created = RechargeRequest.objects.get_or_create(
        chain=network.chain,
        tx_hash=item.tx_hash,
        log_index=int(item.log_index),
        defaults={
            "user": address_row.user,
            "network": network,
            "user_address": address_row,
            "amount": item.amount,
            "deposit_address": address_row.address,
            "from_address": item.from_address,
            "source_type": RechargeRequest.SOURCE_AUTO,
            "token_contract_address": network.token_contract_address,
            "block_number": item.block_number,
            "confirmations": item.confirmations,
            "raw_payload": item.raw_payload,
        },
    )
    updates: list[str] = []
    if not created:
        if req.user_id != address_row.user_id:
            req.user = address_row.user
            updates.append("user")
        if req.network_id != network.id:
            req.network = network
            updates.append("network")
        if req.user_address_id != address_row.id:
            req.user_address = address_row
            updates.append("user_address")
        if req.amount != item.amount:
            req.amount = item.amount
            updates.append("amount")
        if req.deposit_address != address_row.address:
            req.deposit_address = address_row.address
            updates.append("deposit_address")
        if req.from_address != item.from_address:
            req.from_address = item.from_address
            updates.append("from_address")
        if req.block_number != item.block_number:
            req.block_number = item.block_number
            updates.append("block_number")
        if req.confirmations != item.confirmations:
            req.confirmations = item.confirmations
            updates.append("confirmations")
        if req.raw_payload != item.raw_payload:
            req.raw_payload = item.raw_payload
            updates.append("raw_payload")
        if req.source_type != RechargeRequest.SOURCE_AUTO:
            req.source_type = RechargeRequest.SOURCE_AUTO
            updates.append("source_type")
    else:
        if item.confirmations >= int(network.confirmations_required or 1):
            req.status = RechargeRequest.STATUS_COMPLETED
            req.save(update_fields=["status", "updated_at"])
        address_row.last_seen_at = timezone.now()
        address_row.save(update_fields=["last_seen_at", "updated_at"])
    if updates:
        req.save(update_fields=updates + ["updated_at"])
    return req


def _credit_if_confirmed(network: RechargeNetworkConfig, req: RechargeRequest, *, latest_block: int | None) -> bool:
    if req.credited_transaction_id:
        return False
    confirmations = int(req.confirmations or 0)
    if latest_block is not None and req.block_number is not None:
        confirmations = max(confirmations, int(latest_block) - int(req.block_number) + 1)
        if confirmations != req.confirmations:
            req.confirmations = confirmations
            req.save(update_fields=["confirmations", "updated_at"])
    if confirmations < int(network.confirmations_required or 1):
        if req.status != RechargeRequest.STATUS_PENDING:
            req.status = RechargeRequest.STATUS_PENDING
            req.save(update_fields=["status", "updated_at"])
        return False
    req.credit_to_wallet()
    return True


def sync_network_recharges(network: RechargeNetworkConfig) -> dict[str, int]:
    addresses = list(
        UserRechargeAddress.objects.select_related("user", "network")
        .filter(network=network, status=UserRechargeAddress.STATUS_ACTIVE)
        .order_by("id")
    )
    if not addresses or not network.is_auto_ready:
        return {"detected": 0, "credited": 0, "pending": 0}

    detected = credited = 0
    latest_block: int | None = None
    if network.is_evm:
        client = EvmUsdtClient(network)
        latest_block = client.latest_block()
        start_block = network.scan_from_block
        if start_block is None:
            start_block = max(0, latest_block - 3000)
        scan_to_block = client.stable_scan_to_block(from_block=int(start_block), requested_to_block=latest_block)
        if int(start_block) <= int(scan_to_block):
            for item in client.list_new_transfers(addresses, from_block=int(start_block), to_block=int(scan_to_block)):
                address_row = next((row for row in addresses if row.address == item.to_address), None)
                if address_row is None:
                    continue
                req = _upsert_detected_transfer(network, address_row, item)
                detected += 1
                if _credit_if_confirmed(network, req, latest_block=latest_block):
                    credited += 1
            network.scan_from_block = int(scan_to_block) + 1
            network.save(update_fields=["scan_from_block", "updated_at"])
    else:
        client = TronUsdtClient(network)
        latest_block = client.latest_block()
        for address_row in addresses:
            for raw in client.trc20_transfers_for_address(address_row.address):
                tx_hash = str(raw.get("transaction_id") or "").strip()
                if not tx_hash:
                    continue
                info = client.get_transaction_info(tx_hash)
                block_number = info.get("blockNumber")
                confirmations = 0
                if block_number is not None:
                    confirmations = max(0, latest_block - int(block_number) + 1)
                item = DetectedTransfer(
                    tx_hash=tx_hash,
                    log_index=0,
                    from_address=str(raw.get("from") or ""),
                    to_address=str(raw.get("to") or address_row.address),
                    amount=_normalize_amount(int(raw.get("value") or 0), network.token_decimals),
                    block_number=int(block_number) if block_number is not None else None,
                    confirmations=confirmations,
                    raw_payload=raw,
                )
                req = _upsert_detected_transfer(network, address_row, item)
                detected += 1
                if _credit_if_confirmed(network, req, latest_block=latest_block):
                    credited += 1

    pending_qs = RechargeRequest.objects.filter(
        network=network,
        source_type=RechargeRequest.SOURCE_AUTO,
        credited_transaction__isnull=True,
    )
    for req in pending_qs:
        if _credit_if_confirmed(network, req, latest_block=latest_block):
            credited += 1

    pending = pending_qs.count()
    return {"detected": detected, "credited": credited, "pending": pending}


def _confirm_pending_sweeps(network: RechargeNetworkConfig, client) -> int:
    done = 0
    pending_rows = RechargeRequest.objects.filter(network=network, sweep_status=RechargeRequest.SWEEP_PENDING).exclude(
        sweep_tx_hash=""
    )
    for row in pending_rows:
        status = client.confirm_sweep_receipt(row.sweep_tx_hash)
        if status is True:
            row.mark_swept()
            if row.user_address_id:
                UserRechargeAddress.objects.filter(pk=row.user_address_id).update(last_swept_at=timezone.now())
            done += 1
        elif status is False:
            row.mark_sweep_failed("链上归集交易执行失败")
    return done


def sweep_network_recharges(network: RechargeNetworkConfig) -> dict[str, int]:
    if not network.is_auto_ready or not network.sweep_enabled:
        return {"queued": 0, "completed": 0, "topped_up": 0}
    rows = list(
        UserRechargeAddress.objects.select_related("user", "network")
        .filter(network=network, status=UserRechargeAddress.STATUS_ACTIVE)
        .order_by("id")
    )
    if not rows:
        return {"queued": 0, "completed": 0, "topped_up": 0}

    if network.is_evm:
        client = EvmUsdtClient(network)
    else:
        client = TronUsdtClient(network)

    completed = _confirm_pending_sweeps(network, client)
    queued = topped_up = 0
    for row in rows:
        open_recharges = list(
            RechargeRequest.objects.filter(
                network=network,
                user_address=row,
                credited_transaction__isnull=False,
            ).exclude(sweep_status=RechargeRequest.SWEEP_COMPLETED)
        )
        if not open_recharges:
            continue
        token_balance = client.token_balance(row.address)
        if token_balance < Decimal(str(network.min_sweep_amount_usdt or Decimal("1.00"))):
            continue
        native_balance = client.native_balance(row.address)
        if native_balance < Decimal(str(network.topup_native_amount or Decimal("0"))):
            client.send_native_topup(to_address=row.address, amount=Decimal(str(network.topup_native_amount or Decimal("0"))))
            topped_up += 1
            continue
        derived = _derive_account(network, row.derivation_index)
        sweep_tx_hash = client.send_token_sweep(from_private_key=derived.private_key_hex, from_address=row.address)
        for req in open_recharges:
            req.mark_sweep_pending(sweep_tx_hash)
        queued += 1
    return {"queued": queued, "completed": completed, "topped_up": topped_up}
