import logging

from web3 import Web3

from data_structures import BlacklistPolicy


class HaircutPolicy(BlacklistPolicy):

    def __init__(self, w3: Web3):
        super().__init__(w3)
        self.blacklist = {}

    def check_transaction(self, transaction):
        sender = transaction["from"]
        receiver = transaction["to"]

        if sender in self.blacklist:
            # TODO: different currencies
            sender_balance = self.w3.eth.get_balance(transaction["blockNumber"])
            taint_percentage = self.blacklist[sender]/sender_balance

    def add_to_blacklist(self, address: str, amount: int, currency):
        if address not in self.blacklist:
            self.blacklist[address] = {currency: amount}
        else:
            if currency in self.blacklist[address]:
                self.blacklist[address][currency] += amount
            else:
                self.blacklist[address][currency] = amount

    def get_blacklisted_amount(self, block):
        pass
