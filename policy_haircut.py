from typing import Union
from web3 import Web3

from data_structures import BlacklistPolicy
from ethereum_utils import EthereumUtils

eth_list = ["0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2"]


class HaircutPolicy(BlacklistPolicy):

    def __init__(self, w3: Web3):
        super().__init__(w3)
        self.blacklist = {}
        self.eth_utils = EthereumUtils(w3)
        self.current_block = 0

    def check_transaction(self, transaction_log, transaction):
        sender = transaction["from"]
        receiver = transaction["to"]

        self.current_block = transaction["blockNumber"]

        # if the sender is not blacklisted, disregard the transaction
        if sender in self.blacklist:
            # if any of the sender's ETH is blacklisted, check if any ETH was transferred
            if "ETH" in self.blacklist[sender]:
                if transaction["value"] > 0:
                    # transfer taint from sender to receiver (no need to check for "all", since ETH is tainted immediately
                    self.transfer_taint(sender, receiver, transaction["value"], "ETH")
            # check if the tx was a smart contract invocation
            if transaction_log["logs"]:
                # get all transfers
                transfer_events = self.eth_utils.get_all_events_of_type_in_tx(transaction_log, ["Transfer"])

                # for each transfer
                for transfer_event in transfer_events:
                    token = transfer_event["address"]
                    transfer_sender = transfer_event['args']['from']
                    transfer_receiver = transfer_event['args']['to']

                    # check if "all" flag is set for either sender or receiver, taint all tokens if necessary
                    for account in [transfer_sender, transfer_receiver]:
                        # check if token is in "all"-list
                        if "all" in self.blacklist[account] and not self.is_eth(token):
                            # taint entire balance of this token if not
                            if token not in self.blacklist[account]["all"]:
                                self.add_to_blacklist(account, self.eth_utils.get_token_balance(account, token, self.current_block), token)
                                # add token to "all"-list to mark it as done
                                self.blacklist[account]["all"].append(token)

                    self.transfer_taint(sender, receiver, transfer_event['args']['value'], token)

            # TODO: gas fees

    def transfer_taint(self, from_address: str, to_address: str, amount_sent: int, currency: str):
        # check if ETH or WETH, then calculate the amount that should be tainted
        if self.is_eth(currency):
            taint_proportion = self.blacklist[from_address]["ETH"] / self.get_eth_balance(from_address, self.current_block)
            currency = "ETH"
        else:
            taint_proportion = self.blacklist[from_address][currency] / self.eth_utils.get_token_balance(from_address, currency, self.current_block)

        transferred_amount = amount_sent * taint_proportion
        self.blacklist[from_address][currency] -= transferred_amount
        self.add_to_blacklist(to_address, transferred_amount, currency)

    def is_eth(self, currency: str):
        if currency == "ETH":
            return True
        else:
            return currency in eth_list

    def get_eth_balance(self, address: str, block: int):
        total_balance = 0
        total_balance += self.w3.eth.get_balance(address)

        for token in eth_list:
            total_balance += self.eth_utils.get_token_balance(address, token, block)

        return total_balance

    def remove_from_blacklist(self, address: str, amount: Union[int, float], currency: str):
        """
        Remove the specified amount of the given currency from the given account's blacklisted balance.

        :param address: Ethereum address
        :param amount: amount to be removed
        :param currency: token address
        :return: new blacklisted balance of the given account and token
        """
        self.blacklist[address][currency] -= amount
        new_balance = self.blacklist[address][currency]
        if new_balance <= 0:
            del self.blacklist[address][currency]
        return new_balance

    def add_to_blacklist(self, address: str, amount, currency: str):
        if address not in self.blacklist:
            self.blacklist[address] = {currency: amount}
        else:
            if currency in self.blacklist[address] and currency != "all":
                self.blacklist[address][currency] += amount
            else:
                self.blacklist[address][currency] = amount
        # TODO: blacklist all ETH and WETH if "all" flag is set

    def add_account_to_blacklist(self, address: str):
        """
        Add an entire account to the blacklist.
        The account dict will hold under "all" every currency already tainted.

        :param address: Ethereum address to blacklist
        """
        if address not in self.blacklist:
            self.blacklist[address] = {"all": []}
        else:
            self.blacklist[address]["all"] = []

    def get_blacklisted_amount(self, block):
        pass
