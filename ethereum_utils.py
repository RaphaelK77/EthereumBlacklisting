from typing import List

import web3.exceptions
from web3 import Web3
from web3.datastructures import AttributeDict
from web3.logs import DISCARD
import utils

from abis import event_abis


class EthereumUtils:
    def __init__(self, w3: Web3):
        self.w3 = w3
        self.eth_list = ["0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"]

    def _get_token_balance(self, account: str, token_address: str, block: int = None):
        """
        Retrieves the token balance of the given account at the given block

        :param account: Ethereum account
        :param token_address: Ethereum address of token
        :param block: block to be executed at
        :return: token balance, -1 if it cannot be retrieved
        """

        if block is None:
            block = self.w3.eth.get_block_number()

        token_contract_abi = [
            {"type": "function", "name": "balanceOf", "constant": "true", "payable": "false", "inputs": [{"name": "", "type": "address"}], "outputs": [{"name": "", "type": "uint256"}]}]

        contract = self.w3.eth.contract(address=Web3.toChecksumAddress(token_address), abi=token_contract_abi)

        try:
            balance = contract.functions.balanceOf(account).call({}, block)
        except web3.exceptions.BadFunctionCallOutput:
            balance = -1
        except web3.exceptions.ContractLogicError:
            balance = -2

        return balance

    def get_balance(self, account, currency, block):
        if self.is_eth(currency):
            total_balance = 0
            total_balance += self.w3.eth.get_balance(account, block_identifier=block)

            for token in self.eth_list:
                total_balance += self._get_token_balance(Web3.toChecksumAddress(account), token, block)

            return total_balance
        else:
            return self._get_token_balance(account=account, token_address=currency, block=block)

    def is_eth(self, currency: str):
        if currency == "ETH":
            return True
        else:
            return currency in self.eth_list

    def get_block_receipts(self, block):
        return [utils.format_log_dict(log) for log in self.w3.manager.request_blocking("eth_getBlockReceipts", [block])]

    def get_internal_transactions(self, tx_hash: str, only_internal=True, ignore_eth=True):
        transactions_with_value = []

        internal_txs = self.w3.parity.trace_transaction(tx_hash)

        if internal_txs is None:
            raise web3.exceptions.TransactionNotFound("Trying to get internal transactions for an unknown transaction.")

        for tx in internal_txs:
            if "value" not in tx["action"]:
                continue
            value = int(tx["action"]["value"], base=16)
            # filter out all transactions with 0 value or with the WETH token
            if value > 0:
                sender = tx["action"]["from"]
                receiver = tx["action"]["to"]
                if not ignore_eth or not self.is_eth(sender) and not self.is_eth(receiver):
                    transactions_with_value.append({"args": {"from": Web3.toChecksumAddress(sender), "to": Web3.toChecksumAddress(receiver),
                                                             "value": value}, "address": "ETH", "event": "Internal Transaction"})

        if only_internal:
            return transactions_with_value[1:]
        else:
            return transactions_with_value

    def get_all_events_of_type_in_tx(self, receipt: AttributeDict, event_types: List[str]):
        """
        Retrieves all events of the given types from the logs of the given transaction

        :param receipt: transaction receipt
        :param event_types: the type of the events (Transfer, Swap, Deposit, Withdrawal)
        :return: list of decoded logs
        """
        log_dict = {}

        for event_type in event_types:
            checked_addresses = []

            if event_type not in event_abis:
                # logging.error(f"Could not get events of type {event_type} from transaction; type unkown.")
                continue

            token_contract_abi = event_abis[event_type]

            for log in receipt["logs"]:
                smart_contract = log["address"]
                if smart_contract in checked_addresses:
                    continue
                checked_addresses.append(smart_contract)

                contract_object = self.w3.eth.contract(address=Web3.toChecksumAddress(smart_contract), abi=token_contract_abi)

                if contract_object is None:
                    # logging.warning(f"No ABI found for address {smart_contract}")
                    continue

                # Decode any matching logs
                decoded_logs = contract_object.events[event_type]().processReceipt(receipt, errors=DISCARD)

                for decoded_log in decoded_logs:
                    log_dict[str(decoded_log["logIndex"])] = decoded_log

        return list(log_dict.values())
