import logging
import sys
import time
from abc import abstractmethod, ABC
from typing import Optional, Union

from web3 import Web3

import utils


class BlacklistPolicy(ABC):
    def __init__(self, w3: Web3, logging_level=logging.INFO, log_to_file=False):
        self._blacklist = {}
        """ Dictionary of blacklisted accounts, with a sub-dictionary of the blacklisted currencies of these accounts """
        self.w3 = w3
        """ Web3 instance """
        self._write_queue = []
        self._logger = logging.getLogger(__name__)
        self._logger.setLevel(logging.DEBUG)

        formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")

        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging_level)
        console_handler.setFormatter(formatter)
        self._logger.addHandler(console_handler)

        if log_to_file:
            file_handler = logging.FileHandler("data/blacklist.log")
            file_handler.setFormatter(formatter)
            self._logger.addHandler(file_handler)
        self._tx_log = ""

    @abstractmethod
    def check_transaction(self, transaction_log, transaction, full_block):
        pass

    def get_blacklist(self):
        if self._write_queue:
            self._logger.debug("Writing blacklist, because get_blacklist was called.")
            self.write_blacklist()
        return self._blacklist

    def add_to_blacklist(self, address: str, amount, currency: str, immediately=False):
        """
        Add the specified amount of the given currency to the given account's blacklisted balance.

        :param address: Ethereum address
        :param currency: token address
        :param immediately: if true, write operation will not be queued, but executed immediately
        :param amount: amount to be added
        """
        # add address if not in blacklist
        if address not in self._blacklist:
            self._blacklist[address] = {}

        # add currency to address if not in blacklist
        if currency not in self._blacklist[address]:
            self._blacklist[address][currency] = 0

        if immediately:
            self._blacklist[address][currency] += amount
        else:
            self._queue_write(address, currency, amount)

        self._logger.debug(self._tx_log + f"Added {format(amount, '.2e')} of blacklisted currency {currency} to account {address}.")

    def _queue_write(self, account, currency, amount):
        self._write_queue.append([account, currency, amount])

    def propagate_blacklist(self, start_block, block_amount):
        start_time = time.time()

        if block_amount < 500:
            interval = 10
        elif block_amount < 5000:
            interval = 100
        elif block_amount < 50000:
            interval = 1000
        else:
            interval = 10000

        for i in range(start_block, start_block + block_amount):
            full_block = self.w3.eth.get_block(i, full_transactions=True)
            transactions = full_block["transactions"]
            receipts = self.w3.eth.get_block_receipts(i)

            for transaction, transaction_log in zip(transactions, receipts):
                self.check_transaction(transaction_log=transaction_log, transaction=transaction, full_block=full_block)

            if (i - start_block) % interval == 0 and i - start_block > 0:
                blocks_scanned = i - start_block
                elapsed_time = time.time() - start_time
                blocks_remaining = block_amount - blocks_scanned
                logging.info(
                    f"{blocks_scanned} ({format(blocks_scanned / block_amount * 100, '.2f')})% blocks scanned, " +
                    f" {utils.format_seconds_as_time(elapsed_time)} elapsed ({utils.format_seconds_as_time(blocks_remaining * (elapsed_time / blocks_scanned))} remaining, " +
                    f" {format(blocks_scanned / elapsed_time * 60, '.0f')} blocks/min).")

        end_time = time.time()
        self._logger.info(
            f"Propagation complete. Total time: {utils.format_seconds_as_time(end_time - start_time)}s, performance: {format(block_amount / (end_time - start_time) * 60, '.0f')} blocks/min")

    def is_blacklisted(self, address: str, currency: Optional[str] = None):
        if currency is None:
            return address in self._blacklist
        else:
            return address in self._blacklist and currency in self._blacklist[address]

    @abstractmethod
    def get_blacklisted_amount(self, block=None) -> dict:
        pass

    def print_blacklisted_amount(self):
        blacklisted_amounts = self.get_blacklisted_amount()
        print("{")
        for currency in blacklisted_amounts:
            print(f"\t{currency}:\t{format(blacklisted_amounts[currency], '.5e')},")
        print("}")

    def write_blacklist(self):
        for operation in self._write_queue:
            account = operation[0]
            currency = operation[1]
            amount = operation[2]

            if account not in self._blacklist:
                self._blacklist[account] = {}
            if currency not in self._blacklist[account]:
                self._blacklist[account][currency] = 0

            self._blacklist[account][currency] += amount

            # delete currency from dict if 0
            if self._blacklist[account][currency] <= 0:
                del self._blacklist[account][currency]

                # delete account from dict if no currencies left
                if not self._blacklist[account]:
                    del self._blacklist[account]

        self._write_queue = []
        self._logger.debug("Wrote changes to blacklist.")

    def remove_from_blacklist(self, address: str, amount: Union[int, float], currency: str):
        """
        Remove the specified amount of the given currency from the given account's blacklisted balance.

        :param address: Ethereum address
        :param amount: amount to be removed
        :param currency: token address
        """
        amount = abs(amount)
        self._queue_write(address, currency, -amount)

        self._logger.debug(self._tx_log + f"Removed {format(amount, '.2e')} of blacklisted currency {currency} from account {address}.")
