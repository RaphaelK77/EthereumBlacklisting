import json
import logging
import sys
import time
from abc import abstractmethod, ABC
from typing import Optional, Sequence

from web3 import Web3

import utils
from blacklist import Blacklist
from ethereum_utils import EthereumUtils


class BlacklistPolicy(ABC):
    def __init__(self, w3: Web3, checkpoint_file, log_folder=None, metrics_folder=None):
        self.w3 = w3
        """ Web3 instance """
        self._write_queue = []
        self._logger = logging.getLogger(self.get_policy_name())
        self._logger.setLevel(logging.DEBUG)
        self._current_block = -1
        self._checkpoint_file = checkpoint_file
        self._current_tx = ""
        self.temp_balances = None
        if metrics_folder:
            self.metrics_file = f"{metrics_folder}{self.get_policy_name().replace(' ','_')}.txt"
        else:
            self.metrics_file = None

        formatter = logging.Formatter("%(asctime)s %(name)s [%(levelname)s] %(message)s")

        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(formatter)
        self._logger.addHandler(console_handler)

        self.log_file = f"{log_folder}{self.get_policy_name().replace(' ', '_')}.log"

        if log_folder:
            file_handler = logging.FileHandler(self.log_file)
            file_handler.setFormatter(formatter)
            file_handler.setLevel(logging.DEBUG)
            self._logger.addHandler(file_handler)

        self._tx_log = ""
        self._eth_utils = EthereumUtils(w3, self._logger)

        self._blacklist: Blacklist = self.init_blacklist()

    @abstractmethod
    def init_blacklist(self):
        pass

    @abstractmethod
    def get_policy_name(self):
        pass

    def export_metrics(self, total_eth):
        if self.metrics_file:
            with open(self.metrics_file, "a") as metrics_file_handler:
                unique_accounts = self.get_blacklist_metrics()["UniqueTaintedAccounts"]
                metrics_file_handler.write(f"{self._current_block},{unique_accounts},{format(total_eth, '.5e')}\n")

    def clear_metrics_file(self):
        if self.metrics_file:
            with open(self.metrics_file, "w") as out_file:
                out_file.write("Block,Unique accounts,Total ETH\n")

    def increase_temp_balance(self, account, currency, amount):
        if account not in self.temp_balances:
            self.add_to_temp_balances(account, currency)
        self.temp_balances[account][currency] += amount

        # self._logger.debug(f"Increased temp balance of {currency} by {format(amount, '.2e')} for {account}")

    def reduce_temp_balance(self, account, currency, amount):
        if account not in self.temp_balances:
            self.add_to_temp_balances(account, currency)
        self.temp_balances[account][currency] -= amount

        # self._logger.debug(f"Reduced temp balance of {currency} by {format(amount, '.2e')} for {account}")

    def add_to_temp_balances(self, account, currency, get_balance=False):
        if account is None:
            return

        if account not in self.temp_balances:
            self.temp_balances[account] = {"fetched": []}
        if currency not in self.temp_balances[account]:
            if get_balance:
                balance = self.get_balance(account, currency, self._current_block)
                self.temp_balances[account][currency] = balance
                # self._logger.debug(self._tx_log + f"Added {account} with temp balance {format(balance, '.2e')} of {currency} (block {self._current_block}).")
            else:
                self.temp_balances[account][currency] = 0

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

    def propagate_blacklist(self, start_block, block_amount, load_checkpoint=False):
        start_time = time.time()

        if block_amount < 20:
            interval = 1
        elif block_amount < 200:
            interval = 10
        elif block_amount < 2000:
            interval = 100
        else:
            interval = 500

        loop_start_block = start_block

        if load_checkpoint:
            saved_block, saved_blacklist = self.load_from_checkpoint(self._checkpoint_file)
            # only use loaded data if saved block is between start and end block
            if start_block + block_amount - 1 == saved_block:
                self._logger.info("Target already reached. Exiting.")
                return
            if start_block < saved_block < start_block + block_amount - 1:
                loop_start_block = saved_block
                self._blacklist.set_blacklist(saved_blacklist)
                self._logger.info("Continuing from saved state.")
            else:
                self.clear_log()
                self.clear_metrics_file()
                self._logger.info(f"Saved block {saved_block} is not in the correct range. Starting from start block.")
        else:
            self.clear_log()
            self.clear_metrics_file()

        for i in range(loop_start_block, start_block + block_amount):
            self.check_block(i)

            if (i - start_block) % interval == 0 and i - loop_start_block > 0 and i < start_block + block_amount:
                total_blocks_scanned = i - start_block
                blocks_scanned = i - loop_start_block
                elapsed_time = time.time() - start_time
                blocks_remaining = block_amount - total_blocks_scanned
                self._logger.info(
                    f"{total_blocks_scanned} ({format(total_blocks_scanned / block_amount * 100, '.2f')}%) blocks scanned, " +
                    f" {utils.format_seconds_as_time(elapsed_time)} elapsed ({utils.format_seconds_as_time(blocks_remaining * (elapsed_time / blocks_scanned))} remaining, " +
                    f" {format(blocks_scanned / elapsed_time * 60, '.0f')} blocks/min). Last block: {self._current_block}")
                print("Blacklisted amounts:")
                total_eth = self.print_blacklisted_amount()
                self.save_checkpoint(self._checkpoint_file)
                self.export_metrics(total_eth)

        print("Blacklisted amounts:")
        total_eth = self.print_blacklisted_amount()
        if self.metrics_file:
            self.export_metrics(total_eth)

        print("***** Sanity Check *****")
        self.sanity_check()
        print("Sanity check complete.")

        self.save_checkpoint(self._checkpoint_file)
        end_time = time.time()
        self._logger.info(
            f"Propagation complete. Total time: {utils.format_seconds_as_time(end_time - start_time)}, performance: " +
            f"{format(((block_amount + start_block) - loop_start_block) / (end_time - start_time) * 60, '.0f')} blocks/min")

    def check_block(self, block: int):
        # retrieve all necessary block data
        full_block = self.w3.eth.get_block(block, full_transactions=True)
        transactions: Sequence = full_block["transactions"]
        receipts = self._eth_utils.get_block_receipts(block)
        traces = self.w3.parity.trace_block(block)

        # update progress
        self._current_block = block

        # clear temp balances
        self.temp_balances = {}

        for transaction, transaction_log in zip(transactions, receipts):
            internal_transactions = []

            # update progress
            self._tx_log = f"Transaction https://etherscan.io/tx/{transaction['hash'].hex()} | "
            self._current_tx = transaction['hash'].hex()

            while traces:
                # if transaction["hash"].hex() == "0x78a7bfd00fbdbef41ea4999a5044a2d7a760ab39236b16c2b672c406ccda5b56":
                #     print("here")
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

            try:
                self.check_transaction(transaction_log=transaction_log, transaction=transaction, full_block=full_block, internal_transactions=internal_transactions)
            except Exception as e:
                self._logger.error(self._tx_log + f"Exception '{e}' occurred while processing transaction.")
                raise e

    def check_transaction(self, transaction_log, transaction, full_block, internal_transactions):
        sender = transaction["from"]
        receiver = transaction["to"]

        # skip failed transactions
        if transaction_log["status"] == 0:
            # self._logger.debug(self._tx_log + "Smart contract/transaction execution failed, only checking gas.")
            self.check_gas_fees(transaction_log, transaction, full_block, sender)
            return

        # skip the remaining code if there were no smart contract events
        if not transaction_log["logs"] and len(internal_transactions) < 2:
            if internal_transactions:
                self.process_event(internal_transactions[0])

            # if the sender (still) has any blacklisted ETH, taint the paid gas fees
            self.check_gas_fees(transaction_log, transaction, full_block, sender)
            return

        # get all transfers
        events = self._eth_utils.get_all_events_of_type_in_tx(transaction_log, ["Transfer", "Deposit", "Withdrawal"])

        is_weth_transaction = self._eth_utils.is_weth(receiver)

        # internal transactions to and from WETH need to match an event, so they cannot be processed alone
        if transaction["value"] and not is_weth_transaction:
            # process first internal transaction if the transaction transfers ETH
            if not internal_transactions:
                self._logger.error(self._tx_log + f"No internal transactions found for transaction with value {format(transaction['value'], '.2e')}.")
                exit(-1)
            self.process_event(internal_transactions.pop(0))

        for event in events:
            # ignore deposit and withdrawal events from other addresses than WETH
            if event["event"] == "Deposit" and self._eth_utils.is_weth(event["address"]):
                if event["args"]["wad"] > 0:
                    while internal_transactions[0]["event"] != "Deposit":
                        self.process_event(internal_transactions.pop(0))
                    internal_transactions.pop(0)
            elif event["event"] == "Withdrawal" and self._eth_utils.is_weth(event["address"]):
                if event["args"]["wad"] > 0:
                    while internal_transactions[0]["event"] != "Withdrawal":
                        self.process_event(internal_transactions.pop(0))
                    internal_transactions.pop(0)

            self.process_event(event)

        # process any remaining internal transactions
        for internal_tx in internal_transactions:
            if internal_tx["event"] == "Deposit" or internal_tx["event"] == "Withdrawal":
                self._logger.warning(self._tx_log + f"Unaccounted for event of type {internal_tx['event']}.")
                exit(-1)
            self.process_event(internal_tx)

        self.check_gas_fees(transaction_log, transaction, full_block, sender)

    def process_event(self, event):
        if event["event"] == "Deposit":
            dst = event["args"]["dst"]
            value = event["args"]["wad"]
            if not self._eth_utils.is_weth(event["address"]):
                return

            self.add_to_temp_balances(dst, "ETH")
            self.add_to_temp_balances(dst, self._eth_utils.WETH)

            transferred_amount = self.transfer_taint(dst, dst, value, "ETH", self._eth_utils.WETH)

            if transferred_amount > 0:
                self._logger.debug(self._tx_log + f"Processed Withdrawal. Converted {format(transferred_amount, '.2e')} tainted ({format(value, '.2e')} total) ETH of {dst} to WETH.")

            self.reduce_temp_balance(dst, "ETH", value)
            self.increase_temp_balance(dst, self._eth_utils.WETH, value)

        elif event["event"] == "Withdrawal":
            src = event["args"]["src"]
            value = event["args"]["wad"]
            if not self._eth_utils.is_weth(event["address"]):
                return

            self.add_to_temp_balances(src, "ETH")
            self.add_to_temp_balances(src, self._eth_utils.WETH)

            transferred_amount = self.transfer_taint(src, src, value, self._eth_utils.WETH, "ETH")

            if transferred_amount > 0:
                self._logger.debug(self._tx_log + f"Processed Withdrawal. Converted {format(transferred_amount, '.2e')} tainted ({format(value, '.2e')} total) WETH of {src} to ETH.")

            self.increase_temp_balance(src, "ETH", value)
            self.reduce_temp_balance(src, self._eth_utils.WETH, value)

        # Transfer event, incl. internal transactions
        else:
            currency = event["address"]
            if currency != "ETH":
                currency = Web3.toChecksumAddress(currency)
            transfer_sender = event['args']['from']
            transfer_receiver = event['args']['to']
            amount = event['args']['value']

            for account in transfer_sender, transfer_receiver:
                # skip null address
                if account == self._eth_utils.null_address:
                    continue

                if currency != "ETH" and self.is_blacklisted(address=account, currency="all"):
                    self.fully_taint_token(account, currency)

                self.add_to_temp_balances(account, currency)

            # if the sender is blacklisted, transfer taint to receiver
            self.transfer_taint(transfer_sender, transfer_receiver, amount, currency)

            # update balances
            if transfer_sender != self._eth_utils.null_address:
                self.reduce_temp_balance(transfer_sender, currency, amount)
            if transfer_receiver != self._eth_utils.null_address:
                self.increase_temp_balance(transfer_receiver, currency, amount)

            # self._logger.debug(self._tx_log + f"Transferred {format(amount, '.2e')} temp balance of {currency} from {transfer_sender} to {transfer_receiver} ")

        return

    def get_blacklist(self):
        return self._blacklist.get_blacklist()

    def fully_taint_token(self, account, currency, overwrite=False, block=None):
        if block is None:
            block = self._current_block
        # taint entire balance of this token if not already done
        if currency not in self.get_blacklist_value(account, "all") or overwrite:
            entire_balance = self.get_balance(account, currency, block)
            # add token to "all"-list to mark it as done
            self.add_currency_to_all(account, currency)
            # do not add the token to the blacklist if the balance is 0, 0-values in the blacklist can lead to issues
            if entire_balance > 0:
                self.add_to_blacklist(address=account, amount=entire_balance, currency=currency)
                self._logger.info(self._tx_log + f"Tainted entire balance ({format(entire_balance, '.2e')}) of token {currency} for account {account}.")

    def add_to_blacklist(self, address: str, amount: int, currency: str, total_amount: int = None):
        """
        Add the specified amount of the given currency to the given account's blacklisted balance.

        :param total_amount: optional total amount for fifo
        :param address: Ethereum address
        :param currency: token address
        :param amount: amount to be added
        """
        self._blacklist.add_to_blacklist(address, currency=currency, amount=amount, total_amount=total_amount)

        self._logger.debug(self._tx_log + f"Added {format(amount, '.2e')} of blacklisted currency {currency} to account {address}.")

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
            currency_address = currency
            name, symbol = "Ether", "ETH"
            if currency != "ETH":
                name, symbol = self._eth_utils.get_contract_name_symbol(currency)
            else:
                currency_address = "n/a"
            if symbol is None:
                symbol = "n/a"
            if name is None:
                name = "n/a"
            print(f"\t{name: <25}\t{symbol: <5} ({currency_address: <42}):\t{format(blacklisted_amounts[currency], '.5e')},")
        if self._eth_utils.WETH not in blacklisted_amounts:
            blacklisted_amounts[self._eth_utils.WETH] = 0
        if "ETH" not in blacklisted_amounts:
            blacklisted_amounts["ETH"] = 0
        total_eth = blacklisted_amounts['ETH'] + blacklisted_amounts[self._eth_utils.WETH]
        print(f"\t{'Ether + Wrapped Ether': <25}\t{'ETH + WETH:': <49}" +
              f"\t{format(total_eth, '.5e')},")
        print("}")
        return total_eth

    def remove_from_blacklist(self, address: str, amount: int, currency: str):
        """
        Remove the specified amount of the given currency from the given account's blacklisted balance.

        :param address: Ethereum address
        :param amount: amount to be removed
        :param currency: token address
        """
        ret_val = self._blacklist.remove_from_blacklist(address, amount, currency)

        self._logger.debug(self._tx_log + f"Removed {format(amount, '.2e')} of blacklisted currency {currency} from account {address}.")

        return ret_val

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

    def add_account_to_blacklist(self, address: str, block: int):
        """
        Add an entire account to the blacklist.
        The account dict will hold under "all" every currency already tainted.

        :param address: Ethereum address to blacklist
        :param block: block at which the current balance should be blacklisted
        """
        self._blacklist.add_account_to_blacklist(address, block)

        # blacklist all ETH
        eth_balance = self.get_balance(account=address, currency="ETH", block=block)
        self.add_to_blacklist(address, amount=eth_balance, currency="ETH")

        # blacklist all WETH
        self.fully_taint_token(address, self._eth_utils.WETH, overwrite=True, block=block)

        self._logger.info(f"Added entire account of {address} to the blacklist.")
        self._logger.info(f"Blacklisted entire balance of {format(eth_balance, '.2e')} wei (ETH) of account {address}")

    @abstractmethod
    def transfer_taint(self, from_address: str, to_address: str, amount_sent: int, currency: str, currency_2=None) -> int:
        pass

    @abstractmethod
    def check_gas_fees(self, transaction_log, transaction, full_block, sender):
        pass

    def sanity_check(self):
        full_blacklist = self.get_blacklist()

        if self.is_blacklisted(self._eth_utils.null_address):
            self._logger.warning(f"Null address is blacklisted. Values: {full_blacklist[self._eth_utils.null_address]}")
        for account in full_blacklist:
            for currency in full_blacklist[account]:
                if currency == "all":
                    continue
                blacklist_value = self.get_blacklist_value(account, currency)
                balance = self.get_balance(account, currency, self._current_block + 1)
                if blacklist_value > balance:
                    self._logger.warning(f"Blacklist value {format(blacklist_value, '.2e')} for account {account} and currency {currency} is greater than balance {format(balance, '.2e')} " +
                                         f"(difference: {format(blacklist_value - balance, '.2e')})")

    def get_temp_balance(self, account, currency) -> int:
        if account not in self.temp_balances or currency not in self.temp_balances[account]:
            self.add_to_temp_balances(account, currency)
        if currency not in self.temp_balances[account]["fetched"]:
            self.temp_balances[account][currency] += self.get_balance(account, currency, self._current_block)
            self.temp_balances[account]["fetched"].append(currency)

        return self.temp_balances[account][currency]
