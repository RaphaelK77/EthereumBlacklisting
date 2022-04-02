import logging
import time
from abc import abstractmethod, ABC

from web3 import Web3
from web3 import constants

import utils


class Transaction:
    def __init__(self, transaction: dict):
        self.hash = transaction["hash"].hex()
        self.sender = transaction["from"]
        if "to_sc" in transaction:
            self.receiver = transaction["to_sc"]
        else:
            self.receiver = transaction["to"]
        self.amount = transaction["value"]
        self.block = transaction["blockNumber"]
        if "function" in transaction:
            self.function = transaction["function"]
        else:
            self.function = None
        self.swap_path = None

    def __repr__(self):
        if self.function:
            string = f"TX {self.hash}: Function invocation '{self.function}' of contract {self.receiver} by {self.sender} in block {self.block}."
            if self.is_swap():
                string += f" Swap with path {self.swap_path}."
            return string
        return f"TX {self.hash}: Transaction of {self.amount / constants.WEI_PER_ETHER} ETH from {self.sender} to {self.receiver} in block {self.block}."

    def is_swap(self):
        if not self.function:
            return False
        return "swap" in self.function.lower()

    def is_liquidity_operation(self):
        if not self.function:
            return False
        return "liquidity" in self.function.lower()


class BlacklistPolicy(ABC):
    def __init__(self, w3: Web3):
        self.blacklist = []
        self.w3 = w3

    @abstractmethod
    def check_transaction(self, transaction_log, transaction):
        pass

    @abstractmethod
    def add_to_blacklist(self, address: str, amount, currency: str):
        pass

    def propagate_blacklist(self, start_block, block_amount):
        start_time = time.time()

        if block_amount < 50000:
            interval = 1000
        else:
            interval = 10000

        for i in range(start_block, start_block + block_amount):
            transactions = self.w3.eth.get_block(i, full_transactions=True)["transactions"]
            if transactions:
                [self.check_transaction(t, None) for t in transactions]
            if i % interval == 0 and i - start_block > 0:
                blocks_scanned = i - start_block
                elapsed_time = time.time() - start_time
                blocks_remaining = block_amount - blocks_scanned
                logging.info(
                    f"{blocks_scanned} ({format(blocks_scanned / block_amount * 100, '.2f')})% blocks scanned, " +
                    f" {format(elapsed_time, '.2f')}s elapsed ({utils.format_seconds_as_time(blocks_remaining * (elapsed_time / blocks_scanned))} remaining, " +
                    f" {format(blocks_scanned / elapsed_time, '.0f')} blocks/s).")

        end_time = time.time()
        logging.info(f"Propagation complete. Total time: {format(end_time - start_time, '.2f')}s, performance: {format(block_amount / (end_time - start_time), '.0f')} blocks/s")

    @abstractmethod
    def get_blacklisted_amount(self, block):
        pass
