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
                if transaction_log["value"] > 0:
                    # transfer taint from sender to receiver
                    pass
            # check if the tx was a smart contract invocation
            # get all transfers
            # for each transfer
            # check if "all" flag is set
            # check if token is in "all"-list
            # taint get_balance of this token if not
            # TODO: gas fees

            sender_balance = self.w3.eth.get_balance(transaction_log["blockNumber"])
            taint_percentage = self.blacklist[sender] / sender_balance

    def transfer_taint(self, from_address: str, to_address: str, amount: int, currency: str):
        if self.is_eth(currency):
            taint_proportion = self.blacklist[from_address]["ETH"] / self.get_eth_balance(from_address)
        # TODO: implement

    def is_eth(self, currency: str):
        if currency == "ETH":
            return True
        else:
            return currency in eth_list

    def get_eth_balance(self, address: str):
        total_balance = 0
        total_balance += self.w3.eth.get_balance(address)

        for token in eth_list:
            total_balance += self.eth_utils.get_token_balance(address, token, self.current_block)

        return total_balance

    def add_to_blacklist(self, address: str, amount: int, currency: str):
        if address not in self.blacklist:
            self.blacklist[address] = {currency: amount}
        else:
            if currency in self.blacklist[address] and currency != "all":
                self.blacklist[address][currency] += amount
            else:
                self.blacklist[address][currency] = amount
        # TODO: blacklist all ETH and WETH

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
