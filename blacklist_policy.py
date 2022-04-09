import datetime
import json
import logging
import sys
import time
from abc import abstractmethod, ABC
from typing import Optional, Union

from web3 import Web3

import utils
from blacklist import Blacklist
from database import Database
from ethereum_utils import EthereumUtils

log_file = "data/blacklist.log"
log_database = "data/logs.db"


class BlacklistPolicy(ABC):
    def __init__(self, w3: Web3, checkpoint_file, blacklist: Blacklist, logging_level=logging.INFO, log_to_file=False, log_to_db=False):
        self._blacklist: Blacklist = blacklist
        self.w3 = w3
        """ Web3 instance """
        self._write_queue = []
        self._logger = logging.getLogger(__name__)
        self._logger.setLevel(logging.DEBUG)
        self._eth_utils = EthereumUtils(w3)
        self._current_block = -1
        self._checkpoint_file = checkpoint_file
        self._current_tx: str = ""
        self._log_to_db = log_to_db
        self.log_file = log_file

        # only init database if db logging is enabled
        if self._log_to_db:
            self._database = Database(log_database)
            self._database.clear_logs()
        else:
            self._database = None

        formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")

        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging_level)
        console_handler.setFormatter(formatter)
        self._logger.addHandler(console_handler)

        if log_to_file:
            file_handler = logging.FileHandler(self.log_file)
            file_handler.setFormatter(formatter)
            file_handler.setLevel(logging.DEBUG)
            self._logger.addHandler(file_handler)
        self._tx_log = ""

    @abstractmethod
    def check_transaction(self, transaction_log, transaction, full_block, internal_transactions):
        pass

    def clear_log(self):
        open(self.log_file, "w").close()

    def save_checkpoint(self, file_path):
        data = {"block": self._current_block, "blacklist": self._blacklist.get_blacklist()}

        with open(file_path, "w") as outfile:
            json.dump(data, outfile)

        self._logger.info(f"Successfully exported blacklist to {file_path}.")

    def export_blacklist(self, target_file):
        with open(target_file, "w") as outfile:
            json.dump(self._blacklist.get_blacklist(), outfile)

        self._logger.info(f"Successfully exported blacklist to {target_file}.")

    def load_from_checkpoint(self, file_path):
        try:
            with open(file_path, "r") as checkpoint:
                data = json.load(checkpoint)
        except FileNotFoundError:
            self._logger.info(f"No file found under path {file_path}. Continuing without loading checkpoint.")
            return 0, {}
        last_block = data["block"]
        saved_blacklist = data["blacklist"]
        self._logger.info(f"Loading saved data from {file_path}. Last block was {last_block}.")
        return last_block, saved_blacklist

    def check_block(self, block: int):
        full_block = self.w3.eth.get_block(block, full_transactions=True)
        transactions = full_block["transactions"]
        receipts = self._eth_utils.get_block_receipts(block)
        traces = self.w3.parity.trace_block(block)

        for transaction, transaction_log in zip(transactions, receipts):
            internal_transactions = []
            while traces:
                # exclude block rewards
                if "transactionHash" not in traces[0]:
                    traces.pop(0)
                    continue
                # find traces matching the current transaction
                elif traces[0]["transactionHash"] == transaction["hash"].hex():
                    # process internal tx and make it readable by check_transaction
                    internal_transaction_event = self._eth_utils.internal_transaction_to_event(traces.pop(0))
                    # exclude internal transactions with no value
                    if internal_transaction_event:
                        internal_transactions.append(internal_transaction_event)
                else:
                    break

            self.check_transaction(transaction_log=transaction_log, transaction=transaction, full_block=full_block, internal_transactions=internal_transactions)

    def get_blacklist(self):
        return self._blacklist.get_blacklist()

    def fully_taint_token(self, account, currency):
        # taint entire balance of this token if not
        if currency not in self.get_blacklist_value(account, "all"):
            entire_balance = self.get_balance(account, currency, self._current_block)
            # add token to "all"-list to mark it as done
            self.add_currency_to_all(account, currency)
            # do not add the token to the blacklist if the balance is 0, 0-values in the blacklist can lead to issues
            if entire_balance > 0:
                self.add_to_blacklist(address=account, amount=entire_balance, currency=currency, immediately=True)
                self._logger.info(self._tx_log + f"Tainted entire balance ({format(entire_balance, '.2e')}) of token {currency} for account {account}.")
                self.save_log("INFO", "ADD_ALL", account, None, entire_balance, currency)

    def add_to_blacklist(self, address: str, amount: int, currency: str, immediately=False):
        """
        Add the specified amount of the given currency to the given account's blacklisted balance.

        :param address: Ethereum address
        :param currency: token address
        :param immediately: if true, write operation will not be queued, but executed immediately
        :param amount: amount to be added
        """
        if immediately:
            self._blacklist.add_to_blacklist(address, currency=currency, amount=amount, immediately=immediately)
        else:
            self._blacklist.add_to_blacklist(address, currency=currency, amount=amount)

        self._logger.debug(self._tx_log + f"Added {format(amount, '.2e')} of blacklisted currency {currency} to account {address}.")
        self.save_log("DEBUG", datetime.datetime.now(), self._current_tx, "ADD", None, address, amount, currency)

    def propagate_blacklist(self, start_block, block_amount, load_checkpoint=False):
        start_time = time.time()

        if block_amount < 20:
            interval = 1
        elif block_amount < 500:
            interval = 10
        elif block_amount < 5000:
            interval = 100
        elif block_amount < 50000:
            interval = 1000
        else:
            interval = 10000

        loop_start_block = start_block

        if load_checkpoint:
            saved_block, saved_blacklist = self.load_from_checkpoint(self._checkpoint_file)
            # only use loaded data if saved block is between start and end block
            if start_block < saved_block < start_block + block_amount - 1:
                loop_start_block = saved_block
                self._blacklist.set_blacklist(saved_blacklist)
                self._logger.info("Continuing from saved state.")
            else:
                self.clear_log()
                self._logger.info("Saved block is not in the correct range. Starting from start block.")
        else:
            self.clear_log()

        for i in range(loop_start_block, start_block + block_amount):
            self.check_block(i)

            if (i - start_block) % interval == 0 and i - loop_start_block > 0:
                total_blocks_scanned = i - start_block
                blocks_scanned = i - loop_start_block
                elapsed_time = time.time() - start_time
                blocks_remaining = block_amount - blocks_scanned
                self._logger.info(
                    f"{total_blocks_scanned} ({format(total_blocks_scanned / block_amount * 100, '.2f')}%) blocks scanned, " +
                    f" {utils.format_seconds_as_time(elapsed_time)} elapsed ({utils.format_seconds_as_time(blocks_remaining * (elapsed_time / blocks_scanned))} remaining, " +
                    f" {format(blocks_scanned / elapsed_time * 60, '.0f')} blocks/min). Last block: {self._current_block}")
                print("Blacklisted amounts:")
                self.print_blacklisted_amount()
                self.save_checkpoint(self._checkpoint_file)

        self.save_checkpoint(self._checkpoint_file)
        end_time = time.time()
        self._logger.info(
            f"Propagation complete. Total time: {utils.format_seconds_as_time(end_time - start_time)}, performance: {format(((block_amount + start_block) - loop_start_block) / (end_time - start_time) * 60, '.0f')} blocks/min")

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
        self.save_log("DEBUG", "REMOVE", address, None, abs(amount), currency)

    def get_blacklist_metrics(self):
        return self._blacklist.get_metrics()

    def get_balance(self, account, currency, block) -> int:
        balance = self._eth_utils.get_balance(account, currency, block)
        if balance == -1:
            self._logger.debug(self._tx_log + f"Balance for token {currency} and account {account} could not be retrieved.")
            return 0
        if balance == -2:
            self._logger.debug(self._tx_log + f"Balance of account {account} for token {currency} could not be retrieved. The smart contract does not support 'balanceOf'.")
            return 0
        return balance

    def add_account_to_blacklist(self, address: str, block: int, immediately=False):
        """
        Add an entire account to the blacklist.
        The account dict will hold under "all" every currency already tainted.

        :param immediately: add the account immediately if a buffered dict blacklist is used
        :param address: Ethereum address to blacklist
        :param block: block at which the current balance should be blacklisted
        """
        self._blacklist.add_account_to_blacklist(address, block)

        # blacklist all ETH
        eth_balance = self.get_balance(account=address, currency="ETH", block=block)
        if immediately:
            self.add_to_blacklist(address, amount=eth_balance, currency="ETH", immediately=True)
        else:
            self.add_to_blacklist(address, amount=eth_balance, currency="ETH")

        self._logger.info(f"Added entire account of {address} to the blacklist.")
        self.save_log("INFO", "ADD_ACCOUNT", None, address, None, None)
        self._logger.info(f"Blacklisted entire balance of {format(eth_balance, '.2e')} wei (ETH) of account {address}")
        self.save_log("INFO", "ADD_ALL", None, address, eth_balance, "ETH")

    def save_log(self, level: str, event: str, from_account: Optional[str], to_account: Optional[str], amount: Optional[int], currency: Optional[str], amount_2: Optional[int] = None, message=None):
        if self._log_to_db:
            self._database.save_log(level, datetime.datetime.now(), self._current_tx, event, from_account, to_account, amount, currency, amount_2, message)

    @abstractmethod
    def transfer_taint(self, from_address, to_address, amount_sent, currency):
        pass
