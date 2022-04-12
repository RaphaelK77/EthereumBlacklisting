import functools
from typing import List, Optional, Tuple

import web3.exceptions
from web3 import Web3
from web3.datastructures import AttributeDict
from web3.logs import DISCARD

import abis
import utils
from abis import event_abis


class EthereumUtils:
    def __init__(self, w3: Web3, logger):
        self.w3 = w3
        self.eth_list = ["0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"]
        self.null_address = "0x0000000000000000000000000000000000000000"
        self.WETH = "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2"
        self.logger = logger
        self.current_tx = ""
        self.reverted_traces = []

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

        contract = self.get_smart_contract(token_address, function_types=("BalanceOf",))

        try:
            balance = contract.functions.balanceOf(account).call({}, block)
        except web3.exceptions.BadFunctionCallOutput:
            balance = -1
        except web3.exceptions.ContractLogicError:
            balance = -2

        return balance

    def is_weth(self, address):
        if address is None:
            return False
        return Web3.toChecksumAddress(address) == self.WETH

    @functools.lru_cache(maxsize=1024)
    def get_balance(self, account, currency, block):
        if currency == "ETH":
            return self.w3.eth.get_balance(account, block_identifier=block)
        else:
            return self._get_token_balance(account=account, token_address=currency, block=block)

    def is_eth(self, currency: str):
        if currency == "ETH":
            return True
        else:
            return currency in self.eth_list

    def get_block_receipts(self, block):
        return [utils.format_log_dict(log) for log in self.w3.manager.request_blocking("eth_getBlockReceipts", [block])]

    def internal_transaction_to_event(self, internal_tx):
        """
        Converts a transaction trace into an event that can be processed by check_transaction.
        Filters out internal transactions with no value.

        :param internal_tx: transaction trace, result of trace_block
        :return: internal transaction in event format, None if it does not pass the filter
        """
        if self.current_tx != internal_tx["transactionHash"]:
            self.current_tx = internal_tx["transactionHash"]
            self.reverted_traces = []

        # skip transactions that produced an error
        if "error" in internal_tx:
            self.reverted_traces.append(internal_tx["traceAddress"])
            # self.logger.debug(f"Skipping internal transaction in {internal_tx['transactionHash']}, since it produced the error '{internal_tx['error']}' (trace {internal_tx['traceAddress']}).")
            return None

        if "value" not in internal_tx["action"] or "to" not in internal_tx["action"] or "from" not in internal_tx["action"]:
            return None

        value = int(internal_tx["action"]["value"], base=16)
        if value > 0 and "callType" in internal_tx["action"] and internal_tx["action"]["callType"] == "call":
            # check if this transaction follows a reverted one, pass it if true (check value first to not clog up log file)
            for reverted_trace in self.reverted_traces:
                if all(a == b for a, b in zip(reverted_trace, internal_tx["traceAddress"])):
                    # self.logger.debug(f"Skipping internal transaction in {internal_tx['transactionHash']} with trace {internal_tx['traceAddress']}, " +
                    #                   f"since it follows a reverted int. transaction with trace {reverted_trace}.")
                    return None

            sender = internal_tx["action"]["from"]
            receiver = internal_tx["action"]["to"]

            # detect Deposit and Withdrawal by the involvement of the WETH token address
            event_type = "Internal Transaction"
            if self.is_weth(sender):
                event_type = "Withdrawal"
            if self.is_weth(receiver):
                event_type = "Deposit"
            return {"args": {"from": Web3.toChecksumAddress(sender), "to": Web3.toChecksumAddress(receiver),
                             "value": value}, "address": "ETH", "event": event_type}
        return None

    @functools.lru_cache(4096)
    def get_smart_contract(self, address, abi: dict = None, event_types: tuple = None, function_types: tuple = None):
        if abi is None:
            abi = []
            if event_types:
                for event_type in event_types:
                    if event_type not in abis.event_abis:
                        raise ValueError(f"Tried to get smart contract with an event type that does not exist ('{event_type}')")
                    abi.append(abis.event_abis[event_type][0])
            if function_types:
                for function_type in function_types:
                    if function_type not in abis.function_abis:
                        raise ValueError(f"Tried to get smart contract with a function type that does not exist ('{function_type}')")
                    abi.append(abis.function_abis[function_type][0])

        return self.w3.eth.contract(address=Web3.toChecksumAddress(address), abi=abi)

    def get_all_events_of_type_in_tx(self, receipt: AttributeDict, event_types: List[str]):
        """
        Retrieves all events of the given types from the logs of the given transaction

        :param receipt: transaction receipt
        :param event_types: the type of the events (Transfer, Swap, Deposit, Withdrawal)
        :return: list of decoded logs
        """
        log_dict = {}
        checked_addresses = []
        topics = []

        for event_type in event_types:
            if event_type not in event_abis or event_type not in abis.topics:
                raise ValueError(f"Tried to get all events of an event type that does not exist ('{event_type}')")
            topics.append(abis.topics[event_type])

        logs = [log for log in receipt["logs"] if log["topics"] and log["topics"][0].hex() in topics]

        for log in logs:

            smart_contract = log["address"]
            if smart_contract in checked_addresses:
                continue
            checked_addresses.append(smart_contract)

            contract_object = self.get_smart_contract(smart_contract, event_types=tuple(event_types))

            if contract_object is None:
                continue

            # Decode any matching logs
            for event_type in event_types:
                decoded_logs = contract_object.events[event_type]().processReceipt(receipt, errors=DISCARD)
                for decoded_log in decoded_logs:
                    log_dict[decoded_log["logIndex"]] = decoded_log

        return [log_dict[key] for key in sorted(log_dict)]

    @functools.lru_cache(64)
    def get_contract_name_symbol(self, address: str) -> Tuple[Optional[str], Optional[str]]:
        """
        Retrieves the token name and symbol from a token address

        :param address: Ethereum address
        :return: (name, symbol) as string if available, else None for each unavailable field
        """
        contract = self.get_smart_contract(address=Web3.toChecksumAddress(address), function_types=("Name", "Symbol"))

        name = None
        symbol = None

        try:
            name = contract.functions.name().call()
            symbol = contract.functions.symbol().call()
        except web3.exceptions.BadFunctionCallOutput:
            self.logger.debug(f"Name and/or Symbol for {address} could not be retrieved, since it is not a smart contract.")
        except web3.exceptions.ContractLogicError:
            self.logger.debug(f"Name and/or Symbol function of smart contract at {address} could does not exist.")

        return name, symbol

    def get_swap_tokens(self, contract_address: str):
        """
        Gets the addresses of the token pair of a DEX smart contract

        :param contract_address: address of the smart contract
        :return: token0, token1 / None, None if an error occurs
        """
        token_functions_abi = abis.function_abis["Tokens"]

        contract = self.w3.eth.contract(address=Web3.toChecksumAddress(contract_address), abi=token_functions_abi)

        token0 = None
        token1 = None
        try:
            token0 = contract.functions.token0().call({})
            token1 = contract.functions.token1().call({})
        except web3.exceptions.BadFunctionCallOutput:
            self.logger.warning(f"token0 or token1 function for DEX contract at {contract_address} could not be executed.")
        except web3.exceptions.ContractLogicError:
            self.logger.warning(f"Smart contract at {contract_address} does not support token0 or token1 functions.")

        return token0, token1
