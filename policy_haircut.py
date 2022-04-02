from typing import Union
from web3 import Web3
import logging

from data_structures import BlacklistPolicy
from ethereum_utils import EthereumUtils

eth_list = ["0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"]


class HaircutPolicy(BlacklistPolicy):

    def __init__(self, w3: Web3):
        super().__init__(w3)
        self._blacklist = {}
        self._eth_utils = EthereumUtils(w3)
        self._current_block = 0
        self._write_queue = []
        self._tx_log = ""

    def get_blacklist(self):
        self.write_blacklist()
        return self._blacklist

    def check_transaction(self, transaction_log, transaction):
        sender = transaction["from"]
        receiver = transaction["to"]

        if transaction["blockNumber"] > self._current_block:
            # write changes queued up in the last block
            self.write_blacklist()
        self._current_block = transaction["blockNumber"]

        self._tx_log = f"Transaction {transaction['hash'].hex()} | "

        # if any of the sender's ETH is blacklisted, check if any ETH was transferred
        if sender in self._blacklist and "ETH" in self._blacklist[sender]:
            if transaction["value"] > 0:
                # transfer taint from sender to receiver (no need to check for "all", since ETH is tainted immediately)
                self.transfer_taint(from_address=sender, to_address=receiver, amount_sent=transaction["value"], currency="ETH")

        # check if the tx was a smart contract invocation
        if transaction_log["logs"]:
            # get all transfers
            transfer_events = self._eth_utils.get_all_events_of_type_in_tx(transaction_log, ["Transfer"])

            # for each transfer
            for transfer_event in transfer_events:
                token = transfer_event["address"]
                transfer_sender = transfer_event['args']['from']
                transfer_receiver = transfer_event['args']['to']

                # check if "all" flag is set for either sender or receiver, taint all tokens if necessary
                for account in [transfer_sender, transfer_receiver]:
                    # check if token is in "all"-list
                    if not self.is_eth(token) and account in self._blacklist and "all" in self._blacklist[account]:
                        # taint entire balance of this token if not
                        if token not in self._blacklist[account]["all"]:
                            entire_balance = self._eth_utils.get_token_balance(account, token, self._current_block)
                            self.add_to_blacklist_immediately(address=account, amount=entire_balance, currency=token)
                            # add token to "all"-list to mark it as done
                            self._blacklist[account]["all"].append(token)
                            logging.info(self._tx_log + f"Tainted entire balance ({entire_balance}) of token {token} for account {account}.")

                # skip transfers without a blacklisted sender
                if self.is_eth(token):
                    token = "ETH"
                if transfer_sender in self._blacklist and token in self._blacklist[transfer_sender] and self._blacklist[transfer_sender][token] > 0:
                    self.transfer_taint(transfer_sender, transfer_receiver, transfer_event['args']['value'], token)

                # TODO: gas fees

    def write_blacklist(self):
        for operation in self._write_queue:
            account = operation[0]
            currency = operation[1]
            amount = operation[2]

            self._blacklist[account][currency] += amount

            # TODO: delete if 0

    def queue_write(self, account, currency, amount):
        self._write_queue.append([account, currency, amount])

    def transfer_taint(self, from_address: str, to_address: str, amount_sent: int, currency: str):
        # check if ETH or WETH, then calculate the amount that should be tainted
        if self.is_eth(currency):
            taint_proportion = self._blacklist[from_address]["ETH"] / self.get_eth_balance(from_address, self._current_block)
            currency = "ETH"
        else:
            taint_proportion = self._blacklist[from_address][currency] / self._eth_utils.get_token_balance(account=from_address, token_address=currency, block=self._current_block)

        transferred_amount = amount_sent * taint_proportion
        self.queue_write(from_address, currency, -transferred_amount)
        self.add_to_blacklist(address=to_address, currency=currency, block=self._current_block, amount=transferred_amount)

        logging.info(self._tx_log + f"Transferred {transferred_amount} taint of {currency} from {from_address} to {to_address}")

    def is_eth(self, currency: str):
        if currency == "ETH":
            return True
        else:
            return currency in eth_list

    def get_eth_balance(self, address: str, block: int):
        total_balance = 0
        total_balance += self.w3.eth.get_balance(address)

        for token in eth_list:
            total_balance += self._eth_utils.get_token_balance(address, token, block)

        return total_balance

    def remove_from_blacklist(self, address: str, amount: Union[int, float], currency: str):
        """
        Remove the specified amount of the given currency from the given account's blacklisted balance.

        :param address: Ethereum address
        :param amount: amount to be removed
        :param currency: token address
        """
        self.queue_write(address, currency, -amount)

    def add_to_blacklist(self, address: str, currency: str, block: int, amount: Union[int, float] = -1):
        if address not in self._blacklist:
            self._blacklist[address] = {}

        if currency == "all":
            # finish all pending write operations; WARNING: will cause issues if done mid-block
            self.write_blacklist()
            # blacklist all ETH
            self.add_to_blacklist(address=address, currency="ETH", amount=self.get_eth_balance(address=address, block=block), block=block)
            self._blacklist[address]["all"] = []
        else:
            if currency in self._blacklist[address]:
                self.queue_write(address, currency, amount)
            else:
                self._blacklist[address][currency] = 0
                self.queue_write(address, currency, amount)

    def add_to_blacklist_immediately(self, address: str, currency: str, amount: Union[int, float] = -1):
        if address not in self._blacklist:
            self._blacklist[address] = {}
        if currency in self._blacklist[address]:
            self._blacklist[address][currency] += amount
        else:
            self._blacklist[address][currency] = amount

    def add_account_to_blacklist(self, address: str, block: int):
        """
        Add an entire account to the blacklist.
        The account dict will hold under "all" every currency already tainted.

        :param block: block at which the current balance should be blacklisted
        :param address: Ethereum address to blacklist
        """
        if address not in self._blacklist:
            self._blacklist[address] = {"all": []}
        self._blacklist[address]["ETH"] = self.get_eth_balance(address=address, block=block)

    def get_blacklisted_amount(self, block):
        pass
