import logging

from web3 import Web3

from blacklist_policy import BlacklistPolicy


class PoisonPolicy(BlacklistPolicy):

    def __init__(self, w3: Web3):
        super().__init__(w3)
        self.blacklist = set()

    def check_transaction(self, transaction_log, transaction, full_block):
        sender = transaction_log["from"]
        receiver = transaction_log["to"]
        logging.debug(f"Checking transaction from {sender} to {receiver}...")

        # TODO: transfers

        if sender in self.blacklist and receiver is not None:
            self.add_account_to_blacklist(receiver)
            if logging_enabled:
                logging.info(f"Sender {sender} ({self.blacklist.index(sender) + 1}) is on blacklist, adding receiver {receiver} ({self.blacklist.index(receiver) + 1}).")

    def add_to_blacklist(self, address: str, amount: int, currency):
        self.blacklist.add(address)

    def get_blacklisted_amount(self, block):
        return sum([self.w3.eth.get_balance(account) for account in self.blacklist])
