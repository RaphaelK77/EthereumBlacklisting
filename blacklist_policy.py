import logging
import sys
import time
from abc import abstractmethod, ABC
from typing import Optional, Union

from web3 import Web3

import utils
from blacklist import BufferedDictBlacklist
from ethereum_utils import EthereumUtils

log_file = "data/blacklist.log"


class BlacklistPolicy(ABC):
    def __init__(self, w3: Web3, logging_level=logging.INFO, log_to_file=False):
        self._blacklist = BufferedDictBlacklist()
        self.w3 = w3
        """ Web3 instance """
        self._write_queue = []
        self._logger = logging.getLogger(__name__)
        self._logger.setLevel(logging.DEBUG)
        self._eth_utils = EthereumUtils(w3)

        formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")

        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging_level)
        console_handler.setFormatter(formatter)
        self._logger.addHandler(console_handler)

        if log_to_file:
            open(log_file, "w").close()
            file_handler = logging.FileHandler(log_file)
            file_handler.setFormatter(formatter)
            file_handler.setLevel(logging.DEBUG)
            self._logger.addHandler(file_handler)
        self._tx_log = ""

    @abstractmethod
    def check_transaction(self, transaction_log, transaction, full_block, internal_transactions):
        pass

    def get_blacklist(self):
        return self._blacklist.get_blacklist()

    def add_to_blacklist(self, address: str, amount: int, currency: str, immediately=False):
        """
        Add the specified amount of the given currency to the given account's blacklisted balance.

        :param address: Ethereum address
        :param currency: token address
        :param immediately: if true, write operation will not be queued, but executed immediately
        :param amount: amount to be added
        """
        self._blacklist.add_to_blacklist(address, amount, currency, immediately)

        self._logger.debug(self._tx_log + f"Added {format(amount, '.2e')} of blacklisted currency {currency} to account {address}.")

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
            receipts = self._eth_utils.get_block_receipts(i)
            traces = self.w3.parity.trace_block(i)

            for transaction, transaction_log in zip(transactions, receipts):
                internal_transactions = []
                while traces:
                    if "transactionHash" not in traces[0]:
                        traces.pop(0)
                        continue
                    elif traces[0]["transactionHash"] == transaction["hash"].hex():
                        # process internal tx and make it readable by check_transaction
                        internal_transaction_event = self._eth_utils.internal_transaction_to_event(traces.pop(0))
                        # exclude internal transactions with no value
                        if internal_transaction_event:
                            internal_transactions.append(internal_transaction_event)
                    else:
                        break

                self.check_transaction(transaction_log=transaction_log, transaction=transaction, full_block=full_block, internal_transactions=internal_transactions)

            if (i - start_block) % interval == 0 and i - start_block > 0:
                blocks_scanned = i - start_block
                elapsed_time = time.time() - start_time
                blocks_remaining = block_amount - blocks_scanned
                self._logger.info(
                    f"{blocks_scanned} ({format(blocks_scanned / block_amount * 100, '.2f')}%) blocks scanned, " +
                    f" {utils.format_seconds_as_time(elapsed_time)} elapsed ({utils.format_seconds_as_time(blocks_remaining * (elapsed_time / blocks_scanned))} remaining, " +
                    f" {format(blocks_scanned / elapsed_time * 60, '.0f')} blocks/min).")
                print("Blacklisted amounts:")
                self.print_blacklisted_amount()

        end_time = time.time()
        self._logger.info(
            f"Propagation complete. Total time: {utils.format_seconds_as_time(end_time - start_time)}, performance: {format(block_amount / (end_time - start_time) * 60, '.0f')} blocks/min")

    def is_blacklisted(self, address: str, currency: Optional[str] = None):
        return self._blacklist.is_blacklisted(address, currency)

    def add_currency_to_all(self, address, currency):
        return self._blacklist.add_currency_to_all(address, currency)

    def get_blacklist_value(self, account, currency):
        return self._blacklist.get_account_blacklist_value(account, currency)

    def get_blacklisted_amount(self) -> dict:
        return self._blacklist.get_blacklisted_amount()

    def print_blacklisted_amount(self):
        blacklisted_amounts = self.get_blacklisted_amount()
        print("{")
        for currency in blacklisted_amounts:
            print(f"\t{currency}:\t{format(blacklisted_amounts[currency], '.5e')},")
        print("}")

    def remove_from_blacklist(self, address: str, amount: Union[int, float], currency: str, immediately=False):
        """
        Remove the specified amount of the given currency from the given account's blacklisted balance.

        :param immediately: write immediately if True, else add to queue
        :param address: Ethereum address
        :param amount: amount to be removed
        :param currency: token address
        """
        if immediately:
            self._blacklist.remove_from_blacklist(address, amount, currency, immediately)
        else:
            self._blacklist.remove_from_blacklist(address, amount, currency)

        self._logger.debug(self._tx_log + f"Removed {format(amount, '.2e')} of blacklisted currency {currency} from account {address}.")

    def get_blacklist_metrics(self):
        return self._blacklist.get_metrics()
