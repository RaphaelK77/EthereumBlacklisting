from blacklist import FIFOBlacklist
from blacklist_policy import BlacklistPolicy


class FIFOPolicy(BlacklistPolicy):
    def init_blacklist(self):
        return FIFOBlacklist()

    def transfer_taint(self, from_address, to_address, amount_sent, currency, currency_2=None) -> int:
        if currency_2 is None:
            currency_2 = currency

        transferred_amount = 0

        if self.is_blacklisted(from_address, currency):
            transferred_amount = self.remove_from_blacklist(from_address, amount_sent, currency)

        if self.is_blacklisted(to_address, currency) or transferred_amount > 0:
            self.add_to_blacklist(to_address, transferred_amount, currency_2, amount_sent)

            if currency == currency_2:
                self._logger.debug(self._tx_log + f"Transferred {format(transferred_amount, '.2e')} taint " +
                                   f"({format(amount_sent, '.2e')} total) of {currency} from {from_address} to {to_address}")

        return transferred_amount

    def check_gas_fees(self, transaction_log, transaction, full_block, sender):
        gas_price = transaction["gasPrice"]
        base_fee = full_block["baseFeePerGas"]
        gas_used = transaction_log["gasUsed"]
        miner = full_block["miner"]

        if not (self.is_blacklisted(sender, "ETH") or self.is_blacklisted(miner, "ETH")):
            return

        total_fee_paid = gas_price * gas_used
        paid_to_miner = (gas_price - base_fee) * gas_used

        tainted_fee_to_miner = 0
        tainted_fee = 0

        if self.is_blacklisted(sender, "ETH"):
            tainted_fee_to_miner = self.remove_from_blacklist(sender, paid_to_miner, "ETH")
            # check blacklist status again in case the first remove cleared it
            if self.is_blacklisted(sender, "ETH"):
                tainted_fee = self.remove_from_blacklist(sender, total_fee_paid - paid_to_miner, "ETH")

        self.add_to_blacklist(miner, tainted_fee_to_miner, "ETH", paid_to_miner)

        if tainted_fee > 0:
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

    def get_temp_balance(self, account, currency) -> int:
        # overwrite unnecessary function
        pass
