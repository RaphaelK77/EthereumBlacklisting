import logging

from typing import Union
from web3 import Web3

from blacklist import DictBlacklist
from blacklist_policy import BlacklistPolicy

delayed_write = False


class SeniorityPolicy(BlacklistPolicy):
    def __init__(self, w3: Web3, checkpoint_file, logging_level=logging.INFO, log_to_file=False, log_to_db=False):
        super().__init__(w3, checkpoint_file, DictBlacklist(), logging_level=logging_level, log_to_file=log_to_file, log_to_db=log_to_db)

    def transfer_taint(self, from_address, to_address, amount_sent, currency, currency_2=None):
        transferred_amount = min(amount_sent, self.get_blacklist_value(from_address, currency))

        if currency_2 is None:
            currency_2 = currency

        self.remove_from_blacklist(from_address, transferred_amount, currency)

        if to_address is None or to_address == self._eth_utils.null_address:
            self._logger.info(self._tx_log + f"{amount_sent} tokens were burned, of which {transferred_amount} were blacklisted.")
            return

        self.add_to_blacklist(to_address, transferred_amount, currency_2)

        if currency == currency_2:
            self._logger.debug(self._tx_log + f"Transferred {format(transferred_amount, '.2e')} taint of {currency} from {from_address} to {to_address}")

        return transferred_amount

    def check_gas_fees(self, transaction_log, transaction, full_block, sender):
        gas_price = transaction["gasPrice"]
        base_fee = full_block["baseFeePerGas"]
        gas_used = transaction_log["gasUsed"]
        miner = full_block["miner"]

        total_fee_paid = gas_price * gas_used
        paid_to_miner = (gas_price - base_fee) * gas_used

        tainted_fee = min(total_fee_paid, self.get_blacklist_value(sender, "ETH"))
        tainted_fee_to_miner = min(paid_to_miner, self.get_blacklist_value(sender, "ETH"))

        self.remove_from_blacklist(sender, tainted_fee, "ETH")
        self.add_to_blacklist(miner, tainted_fee_to_miner, "ETH")

        self.reduce_temp_balance(sender, "ETH", total_fee_paid)
        self.increase_temp_balance(miner, "ETH", paid_to_miner)

        self._logger.debug(self._tx_log + f"Fee: Removed {format(tainted_fee, '.2e')} wei taint from {sender}, and transferred {format(tainted_fee_to_miner, '.2e')} wei of which to miner {miner}")

    def increase_temp_balance(self, account, currency, amount):
        # overwrite unnecessary function
        pass

    def reduce_temp_balance(self, account, currency, amount):
        # overwrite unnecessary function
        pass

    def add_to_temp_balances(self, account, currency, get_balance=False):
        # overwrite unnecessary function
        pass
