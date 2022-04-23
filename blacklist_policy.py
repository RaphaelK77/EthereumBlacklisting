import json
import logging
import sys
import time
from abc import abstractmethod, ABC
from typing import Optional, Sequence
import os

from web3 import Web3

import utils
from blacklist import Blacklist
from ethereum_utils import EthereumUtils


class BlacklistPolicy(ABC):
    """
    Abstract superclass defining all functions a blacklist policy needs to implement.
    """

    def __init__(self, w3: Web3, data_folder, export_metrics=True):
        self.w3 = w3
        """ Web3 instance """

        # add slash at end of data folder path if not already there
        if data_folder[-1] != "/":
            data_folder += "/"

        self._write_queue = []
        self._logger = logging.getLogger(self.get_policy_name())
        self._logger.setLevel(logging.DEBUG)
        self._current_block = -1
        self._current_tx = ""
        self.temp_balances = None

        for folder in [f"{data_folder}", f"{data_folder}/checkpoints", f"{data_folder}/analytics", f"{data_folder}/logs"]:
            if not os.path.exists(folder):
                os.makedirs(folder)

        name = self.get_policy_name().replace(' ', '_')
        self._checkpoint_file = f"{data_folder}checkpoints/{name}.json"

        if export_metrics:
            self.metrics_file = f"{data_folder}analytics/{name}.csv"
            self.transaction_metrics_file = f"{data_folder}analytics/{name}_transactions.csv"
        else:
            self.metrics_file = None
            self.transaction_metrics_file = None

        formatter = logging.Formatter("%(asctime)s %(name)s [%(levelname)s] %(message)s")

        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(formatter)
        self._logger.addHandler(console_handler)
        self._tainted_transactions_per_account = {}

        self.log_file = f"{data_folder}logs/{self.get_policy_name().replace(' ', '_')}.log"

        file_handler = logging.FileHandler(self.log_file)
        file_handler.setFormatter(formatter)
        file_handler.setLevel(logging.DEBUG)
        self._logger.addHandler(file_handler)

        self._tx_log = ""
        self._eth_utils = EthereumUtils(w3, self._logger)

        self._blacklist: Blacklist = self.init_blacklist()

    @abstractmethod
    def init_blacklist(self):
        """
        Create the blacklist object
        """
        pass

    @abstractmethod
    def get_policy_name(self):
        """
        :return: the name of the current policy
        """
        pass

    def export_metrics(self, total_eth):
        """
        Export the metrics to the given csv file

        :param total_eth: total blacklisted Ether
        """
        if self.metrics_file:
            with open(self.metrics_file, "a") as metrics_file_handler:
                unique_accounts = self.get_blacklist_metrics()["UniqueTaintedAccounts"]
                total_tainted_transactions = sum([item[1]['incoming'] for item in self._tainted_transactions_per_account.items()])
                metrics_file_handler.write(f"{self._current_block},{unique_accounts},{self._format_exp(total_eth, 5)},{total_tainted_transactions}\n")

    def export_tainted_transactions(self, min_tx):
        if self.transaction_metrics_file:
            with open(self.transaction_metrics_file, "w") as transaction_metrics_file:
                transaction_metrics_file.write("Account,Incoming,Outgoing\n")
                for item in reversed(sorted(self._tainted_transactions_per_account.items(), key=lambda i: i[1]["incoming"] + i[1]["outgoing"])):
                    if item[1]["incoming"] + item[1]["outgoing"] > min_tx:
                        transaction_metrics_file.write(f"{item[0]},{item[1]['incoming']},{item[1]['outgoing']}\n")

    def clear_metrics_file(self):
        """
        Delete the contents of the metrics file.
        Asks for confirmation first.
        """
        if self.metrics_file:
            print("WARNING: clearing metrics file. Enter 'y' to continue.")
            response = input(">> ")
            if response.lower() != "y":
                print("Exiting.")
                exit(0)
            else:
                print("Clearing confirmed. Continuing.")

                with open(self.metrics_file, "w") as out_file:
                    out_file.write("Block,Unique accounts,Total ETH,Tainted transactions\n")

    def _increase_temp_balance(self, account, currency, amount):
        """
        Increase the temp balance of the given account and currency by amount

        :param account: address
        :param currency: token/ETH
        :param amount: amount to increase by
        """
        if account not in self.temp_balances:
            self._add_to_temp_balances(account, currency)
        self.temp_balances[account][currency] += amount

        # self._logger.debug(f"Increased temp balance of {currency} by {format(amount, '.2e')} for {account}")

    def _reduce_temp_balance(self, account, currency, amount):
        """
        Reduce the temp balance of the given account and currency by amount

        :param account: address
        :param currency: token/ETH
        :param amount: amount to reduce by
        """
        if account not in self.temp_balances or currency not in self.temp_balances[account]:
            self._add_to_temp_balances(account, currency)
        self.temp_balances[account][currency] -= amount

        # self._logger.debug(f"Reduced temp balance of {currency} by {format(amount, '.2e')} for {account}")

    def _add_to_temp_balances(self, account, currency, get_balance=False):
        """
        Add the given account & currency to temp balances

        :param account: address
        :param currency: token/ETH
        :param get_balance: if True, fetch the current balance, else only track the changes
        """
        if account is None:
            return

        if account not in self.temp_balances:
            self.temp_balances[account] = {"fetched": []}
        if currency not in self.temp_balances[account]:
            if get_balance:
                balance = self._get_balance(account, currency, self._current_block)
                self.temp_balances[account][currency] = balance
                # self._logger.debug(self._tx_log + f"Added {account} with temp balance {format(balance, '.2e')} of {currency} (block {self._current_block}).")
            else:
                self.temp_balances[account][currency] = 0

    def _clear_log(self):
        """
        Clear the log file
        """
        open(self.log_file, "w").close()

    def _save_checkpoint(self, file_path):
        data = {"block": self._current_block, "blacklist": self._blacklist.get_blacklist(), "tainted transactions": self._tainted_transactions_per_account}

        with open(file_path, "w") as outfile:
            json.dump(data, outfile)

        self._logger.info(f"Successfully exported blacklist to {file_path}.")

    def export_blacklist(self, target_file):
        """
        Export the blacklist in json format

        :param target_file: file to write to
        """
        with open(target_file, "w") as outfile:
            json.dump(self._blacklist.get_blacklist(), outfile)

        self._logger.info(f"Successfully exported blacklist to {target_file}.")

    def load_from_checkpoint(self, file_path):
        try:
            with open(file_path, "r") as checkpoint:
                data = json.load(checkpoint)
        except FileNotFoundError:
            self._logger.info(f"No file found under path {file_path}. Continuing without loading checkpoint.")
            return 0, {}, {}
        last_block = data["block"]
        saved_blacklist = data["blacklist"]
        tainted_transactions = data["tainted transactions"]
        self._logger.info(f"Loading saved data from {file_path}. Last block was {last_block}.")
        return last_block, saved_blacklist, tainted_transactions

    def propagate_blacklist(self, start_block, block_amount, load_checkpoint=False):
        """
        Propagate the blacklist from the start block

        :param start_block: block to start from
        :param block_amount: amount of blocks to propagate for
        :param load_checkpoint: whether the program should attempt to load an existing checkpoint
        """
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
        self._current_block = start_block

        if load_checkpoint:
            saved_block, saved_blacklist, tainted_transactions = self.load_from_checkpoint(self._checkpoint_file)
            # only use loaded data if saved block is between start and end block
            if start_block + block_amount - 1 == saved_block:
                self._logger.info("Target already reached. Exiting.")
                return
            if start_block < saved_block < start_block + block_amount - 1:
                loop_start_block = saved_block
                self._blacklist.set_blacklist(saved_blacklist)
                self._tainted_transactions_per_account = tainted_transactions
                self._logger.info(f"Continuing from saved state. Progress is {format((loop_start_block - start_block) / block_amount * 100, '.2f')}%")
            else:
                self._clear_log()
                self.clear_metrics_file()
                self._logger.info(f"Saved block {saved_block} is not in the correct range. Starting from start block.")
                print("Starting amounts:")
                total_eth = self.print_blacklisted_amount()
                self.export_metrics(total_eth)
        else:
            self._clear_log()
            self.clear_metrics_file()
            print("Starting amounts:")
            total_eth = self.print_blacklisted_amount()
            self.export_metrics(total_eth)

        for i in range(loop_start_block, start_block + block_amount):
            self._process_block(i)

            if (i - start_block) % interval == 0 and i - loop_start_block > 0 and i < start_block + block_amount:
                total_blocks_scanned = i - start_block
                blocks_scanned = i - loop_start_block
                elapsed_time = time.time() - start_time
                blocks_remaining = block_amount - total_blocks_scanned
                self._logger.info(
                    f"{total_blocks_scanned} ({format(total_blocks_scanned / block_amount * 100, '.2f')}%) blocks scanned, " +
                    f" {utils.format_seconds_as_time(elapsed_time)} elapsed ({utils.format_seconds_as_time(blocks_remaining * (elapsed_time / blocks_scanned))} remaining, " +
                    f" {format(blocks_scanned / elapsed_time * 60, '.0f')} blocks/min). Last block: {self._current_block}")
                if self.get_policy_name() != "Poison":
                    print("Blacklisted amounts:")
                    total_eth = self.print_blacklisted_amount()
                else:
                    total_eth = None
                self._save_checkpoint(self._checkpoint_file)
                self.export_metrics(total_eth)
                top_accounts = self._blacklist.get_top_accounts(5, ["ETH", self._eth_utils.WETH])
                if top_accounts:
                    print("Top accounts:")
                    for account in reversed(top_accounts):
                        print(f"\t{account}: {self._format_exp(top_accounts[account])} ETH")

        if self.get_policy_name() != "Poison":
            print("Blacklisted amounts:")
            total_eth = self.print_blacklisted_amount()
            if self.metrics_file:
                self.export_metrics(total_eth)

            print("***** Sanity Check *****")
            self.sanity_check()
            print("Sanity check complete.")

        self._save_checkpoint(self._checkpoint_file)
        end_time = time.time()
        self._logger.info(
            f"Propagation complete. Total time: {utils.format_seconds_as_time(end_time - start_time)}, performance: " +
            f"{format(((block_amount + start_block) - loop_start_block) / (end_time - start_time) * 60, '.0f')} blocks/min")

    def _process_block(self, block: int):
        """
        Check the given block for tainted transactions and change the blacklist accordingly

        :param block: block number
        """
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
                self._process_transaction(transaction_log=transaction_log, transaction=transaction, full_block=full_block, internal_transactions=internal_transactions)
            except Exception as e:
                self._logger.error(self._tx_log + f"Exception '{e}' occurred while processing transaction.")
                raise e

    def _process_transaction(self, transaction_log, transaction, full_block, internal_transactions):
        """
        Processes the given transaction and changes the blacklist accordingly

        :param transaction_log: transaction receipt (list of events)
        :param transaction: full transaction
        :param full_block: full block
        :param internal_transactions: all internal transactions that should be processed
        """
        sender = transaction["from"]
        receiver = transaction["to"]

        # skip failed transactions
        if transaction_log["status"] == 0:
            # self._logger.debug(self._tx_log + "Smart contract/transaction execution failed, only checking gas.")
            self._process_gas_fees(transaction_log, transaction, full_block, sender)
            return

        # skip the remaining code if there were no smart contract events
        if not transaction_log["logs"] and len(internal_transactions) < 2:
            if internal_transactions:
                self._process_event(internal_transactions[0])

            # if the sender (still) has any blacklisted ETH, taint the paid gas fees
            self._process_gas_fees(transaction_log, transaction, full_block, sender)
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
            self._process_event(internal_transactions.pop(0))

        for event in events:
            # ignore deposit and withdrawal events from other addresses than WETH
            if event["event"] == "Deposit" and self._eth_utils.is_weth(event["address"]):
                if event["args"]["wad"] > 0:
                    while internal_transactions[0]["event"] != "Deposit":
                        self._process_event(internal_transactions.pop(0))
                    internal_transactions.pop(0)
            elif event["event"] == "Withdrawal" and self._eth_utils.is_weth(event["address"]):
                if event["args"]["wad"] > 0:
                    while internal_transactions[0]["event"] != "Withdrawal":
                        self._process_event(internal_transactions.pop(0))
                    internal_transactions.pop(0)

            self._process_event(event)

        # process any remaining internal transactions
        for internal_tx in internal_transactions:
            if internal_tx["event"] == "Deposit" or internal_tx["event"] == "Withdrawal":
                self._logger.warning(self._tx_log + f"Unaccounted for event of type {internal_tx['event']}.")
                exit(-1)
            self._process_event(internal_tx)

        self._process_gas_fees(transaction_log, transaction, full_block, sender)

    def _record_tainted_transaction(self, sender, receiver, fee=False):
        """
        Add a tainted transaction to the per-account records

        :param sender: transaction sender
        :param receiver: transaction receiver (can be a miner)
        :param fee: whether the transaction was a mining fee
        """
        if sender not in self._tainted_transactions_per_account:
            self._tainted_transactions_per_account[sender] = {"incoming": 0, "outgoing": 0, "incoming fee": 0, "outgoing fee": 0}
        if receiver not in self._tainted_transactions_per_account:
            self._tainted_transactions_per_account[receiver] = {"incoming": 0, "outgoing": 0, "incoming fee": 0, "outgoing fee": 0}

        if fee:
            self._tainted_transactions_per_account[sender]["outgoing fee"] += 1
            self._tainted_transactions_per_account[receiver]["incoming fee"] += 1
        else:
            self._tainted_transactions_per_account[sender]["outgoing"] += 1
            self._tainted_transactions_per_account[receiver]["incoming"] += 1

    def _process_event(self, event):
        """
        Processes a deposit, withdrawal or transfer event or an internal transaction.
        Update temporary balances and blacklist.

        :param event: event dict
        """
        if event["event"] == "Deposit":
            dst = event["args"]["dst"]
            value = event["args"]["wad"]
            if not self._eth_utils.is_weth(event["address"]):
                return

            self._add_to_temp_balances(dst, "ETH")
            self._add_to_temp_balances(dst, self._eth_utils.WETH)

            transferred_amount = self._transfer_taint(dst, dst, value, "ETH", self._eth_utils.WETH)

            if transferred_amount > 0:
                self._logger.debug(self._tx_log + f"Processed Withdrawal. Converted {self._format_exp(transferred_amount)} tainted ({self._format_exp(value)} total) ETH of {dst} to WETH.")

            self._reduce_temp_balance(dst, "ETH", value)
            self._increase_temp_balance(dst, self._eth_utils.WETH, value)

        elif event["event"] == "Withdrawal":
            src = event["args"]["src"]
            value = event["args"]["wad"]
            if not self._eth_utils.is_weth(event["address"]):
                return

            self._add_to_temp_balances(src, "ETH")
            self._add_to_temp_balances(src, self._eth_utils.WETH)

            transferred_amount = self._transfer_taint(src, src, value, self._eth_utils.WETH, "ETH")

            if transferred_amount > 0:
                self._logger.debug(self._tx_log + f"Processed Withdrawal. Converted {self._format_exp(transferred_amount)} tainted ({self._format_exp(value)} total) WETH of {src} to ETH.")

            self._increase_temp_balance(src, "ETH", value)
            self._reduce_temp_balance(src, self._eth_utils.WETH, value)

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

                self._add_to_temp_balances(account, currency)

            # if the sender is blacklisted, transfer taint to receiver
            transferred_amount = self._transfer_taint(transfer_sender, transfer_receiver, amount, currency)

            if transferred_amount > 0:
                self._record_tainted_transaction(transfer_sender, transfer_receiver)

            # update balances
            if transfer_sender != self._eth_utils.null_address:
                self._reduce_temp_balance(transfer_sender, currency, amount)
            if transfer_receiver != self._eth_utils.null_address:
                self._increase_temp_balance(transfer_receiver, currency, amount)

            # self._logger.debug(self._tx_log + f"Transferred {format(amount, '.2e')} temp balance of {currency} from {transfer_sender} to {transfer_receiver} ")

        return

    def get_blacklist(self):
        """
        Retrieves the full blacklist

        :return: the blacklist as the respective data structure
        """
        return self._blacklist.get_blacklist()

    def fully_taint_token(self, account, currency, overwrite=False, block=None):
        """
        Taints the account's entire balance of the given token

        :param account: Ethereum account
        :param currency: token address (ETH is not valid)
        :param overwrite: if True, will taint the entire balance even if it has been tainted before
        :param block: block at which to get the balance
        """
        if block is None:
            block = self._current_block
        # taint entire balance of this token if not already done
        if currency not in self.get_blacklist_value(account, "all") or overwrite:
            entire_balance = self._get_balance(account, currency, block)
            # add token to "all"-list to mark it as done
            self._add_currency_to_all(account, currency)
            # do not add the token to the blacklist if the balance is 0, 0-values in the blacklist can lead to issues
            if entire_balance > 0:
                self.add_to_blacklist(address=account, amount=entire_balance, currency=currency, total_amount=entire_balance)
                self._logger.info(self._tx_log + f"Tainted entire balance ({self._format_exp(entire_balance)}) of token {currency} for account {account}.")

    def add_to_blacklist(self, address: str, amount: int, currency: str, total_amount: int = None):
        """
        Add the specified amount of the given currency to the given account's blacklisted balance.

        :param total_amount: optional total amount for fifo
        :param address: Ethereum address
        :param currency: token address
        :param amount: amount to be added
        """
        # do not taint null address
        if address == self._eth_utils.null_address:
            return
        self._blacklist.add_to_blacklist(address, currency=currency, amount=amount, total_amount=total_amount)

        if amount > 0 and self.get_policy_name() != "Haircut":
            self._logger.debug(self._tx_log + f"Added {self._format_exp(amount)} of blacklisted currency {currency} to account {address}.")

    def is_blacklisted(self, address: str, currency: Optional[str] = None) -> bool:
        """
        Check if the address possesses any blacklisted value of given currency

        :param address: Ethereum address
        :param currency: token or ETH; if not given, checks if account has any blacklisted currency
        :return: True if in blacklist
        """
        return self._blacklist.is_blacklisted(address, currency)

    def _add_currency_to_all(self, address, currency):
        return self._blacklist.add_currency_to_all(address, currency)

    def get_blacklist_value(self, account, currency):
        return self._blacklist.get_account_blacklist_value(account, currency)

    def get_blacklisted_amount(self) -> dict:
        """
        Get the total blacklisted amounts for each currency

        :return: dict of currency: amount
        """
        return self._blacklist.get_blacklisted_amount()

    def print_blacklisted_amount(self):
        """
        Print the total blacklisted amounts for each currency

        :return: total blacklisted ETH (ETH & WETH)
        """
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

        if ret_val > 0 and self.get_policy_name() != "Haircut":
            self._logger.debug(self._tx_log + f"Removed {self._format_exp(ret_val)} of blacklisted currency {currency} from account {address}.")
        elif ret_val == -1:
            self._logger.debug(self._tx_log + f"Removed address {address} from blacklist.")

        return ret_val

    def get_tainted_transactions_per_account(self):
        return self._tainted_transactions_per_account

    def get_blacklist_metrics(self):
        """
        Retrieve the underlying blacklist's metrics

        :return: dict of metric: value
        """
        return self._blacklist.get_metrics()

    def _get_balance(self, account, currency, block) -> int:
        """
        Retrieve the balance of the given account and currency at the given block

        :param account: Ethereum account
        :param currency: token address/ETH
        :param block: block number
        :return: balance, 0 if an error occurred
        """
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
        eth_balance = self._get_balance(account=address, currency="ETH", block=block)
        self.add_to_blacklist(address, amount=eth_balance, currency="ETH", total_amount=eth_balance)

        # blacklist all WETH
        self.fully_taint_token(address, self._eth_utils.WETH, overwrite=True, block=block)

        self._logger.info(f"Added entire account of {address} to the blacklist.")
        self._logger.info(f"Blacklisted entire balance of {self._format_exp(eth_balance)} wei (ETH) of account {address}")

    @abstractmethod
    def _transfer_taint(self, from_address: str, to_address: str, amount_sent: int, currency: str, currency_2: str = None) -> int:
        """
        Calculate the taint to be transferred and adjust the blacklist accordingly.
        Different implementation for every policy.

        :param from_address: sender address
        :param to_address: receiver address
        :param amount_sent: the amount sent
        :param currency: the sent currency
        :param currency_2: optional, gives the receiver a different currency than was sent, used for ETH-WETH conversion
        :return: amount of taint actually transferred
        """
        pass

    @abstractmethod
    def _process_gas_fees(self, transaction_log, transaction, full_block, sender):
        """
        Process any taint transferred by the gas fees of the given transaction.
        Different implementation for every policy.

        :param transaction_log: transaction receipt
        :param transaction: full transaction
        :param full_block: full block
        :param sender: transaction sender
        """
        pass

    def sanity_check(self):
        """
        Checks for any possible inconsistencies as a result of taint propagation.
        Emits warnings it any are found.
        """

        full_blacklist = self.get_blacklist()

        if self.is_blacklisted(self._eth_utils.null_address):
            self._logger.warning(f"Null address is blacklisted. Values: {full_blacklist[self._eth_utils.null_address]}")
        for account in full_blacklist:
            for currency in full_blacklist[account]:
                if currency == "all":
                    continue
                blacklist_value = self.get_blacklist_value(account, currency)
                balance = self._get_balance(account, currency, self._current_block + 1)
                if blacklist_value > balance:
                    self._logger.warning(f"Blacklist value {self._format_exp(blacklist_value)} for account {account} and currency {currency} is greater than balance {self._format_exp(balance)} " +
                                         f"(difference: {self._format_exp(blacklist_value - balance)})")

    def _get_temp_balance(self, account, currency) -> int:
        """
        Retrieve the temp balance for the given account and currency.
        Fetch the actual balance if not done yet.

        :param account: Ethereum account
        :param currency: token address or ETH
        :return: temp balance as int
        """
        if account not in self.temp_balances or currency not in self.temp_balances[account]:
            self._add_to_temp_balances(account, currency)
        if currency not in self.temp_balances[account]["fetched"]:
            self.temp_balances[account][currency] += self._get_balance(account, currency, self._current_block)
            self.temp_balances[account]["fetched"].append(currency)

        return self.temp_balances[account][currency]

    def _format_exp(self, number: Optional[int], decimals: int = 2) -> str:
        """
        Format number in exponential format

        :param number: number to be formatted
        :param decimals: numbers after comma, defaults to 2
        :return: number formatted as str
        """
        if number is None:
            return ""
        return self._eth_utils.format_exponential(number, decimals)

    def print_tainted_transactions_per_account(self, number=10):
        """
        Print the top number accounts by total amount of tainted transactions

        :param number: how many accounts (at most)
        """
        result_dict = dict(reversed(sorted(self._tainted_transactions_per_account.items(), key=lambda item: item[1]["incoming"] + item[1]["outgoing"])))

        if len(result_dict) > number:
            items = list(result_dict.items())[:number]
        else:
            items = result_dict.items()

        for item in items:
            print(f"\t{item[0]}:\t{item[1]}")

        print(f"\tTotal: {sum([item[1]['incoming'] for item in result_dict.items()])} tainted transactions")

        return
