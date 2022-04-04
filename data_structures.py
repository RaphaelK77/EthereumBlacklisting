import logging
import time
from abc import abstractmethod, ABC
from typing import Optional

from web3 import Web3

import utils


class BlacklistPolicy(ABC):
    def __init__(self, w3: Web3):
        self._blacklist = {}
        """ Dictionary of blacklisted accounts, with a sub-dictionary of the blacklisted currencies of these accounts """
        self.w3 = w3

    @abstractmethod
    def check_transaction(self, transaction_log, transaction, block):
        pass

    @abstractmethod
    def add_to_blacklist(self, address: str, amount, currency: str, block: int):
        pass

    def propagate_blacklist(self, start_block, block_amount):
        # TODO: change to use get_block_receipts
        start_time = time.time()

        if block_amount < 50000:
            interval = 1000
        else:
            interval = 10000

        for i in range(start_block, start_block + block_amount):
            transactions = self.w3.eth.get_block(i, full_transactions=True)["transactions"]
            if transactions:
                [self.check_transaction(t, None, None) for t in transactions]
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

    def is_blacklisted(self, address: str, currency: Optional[str] = None):
        if currency is None:
            return address in self._blacklist
        else:
            return address in self._blacklist and currency in self._blacklist[address]

    @abstractmethod
    def get_blacklisted_amount(self, block):
        pass
