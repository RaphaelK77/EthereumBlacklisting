import logging

from web3 import Web3

from blacklist import DictBlacklist
from blacklist_policy import BlacklistPolicy


class SeniorityPolicy(BlacklistPolicy):
    def __init__(self, w3: Web3, logging_level=logging.INFO, log_to_file=False):
        super().__init__(w3, DictBlacklist(), logging_level, log_to_file)

    def check_transaction(self, transaction_log, transaction, full_block, internal_transactions):
        pass

    def add_account_to_blacklist(self, address: str, block: int, immediately=False):
        super().add_account_to_blacklist(address, block)
