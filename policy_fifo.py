from blacklist import FIFOBlacklist
from blacklist_policy import BlacklistPolicy


class FIFOPolicy(BlacklistPolicy):
    def init_blacklist(self):
        return FIFOBlacklist()

    def get_policy_name(self):
        return "FIFO"

    def transfer_taint(self, from_address, to_address, amount_sent, currency, currency_2=None) -> int:
        if currency_2 is None:
            currency_2 = currency

        transferred_amount = 0

        if self.is_blacklisted(from_address, currency):
            # amount by which the balance is higher than the blacklisted value
            difference = self.get_temp_balance(from_address, currency) - self.get_blacklist_value(from_address, currency)
            if difference < 0:
                self._logger.warning(f"Blacklist value {self.format_exp(self.get_blacklist_value(from_address, currency))} for account {from_address} is higher than " +
                                     f"temp balance {self.format_exp(self.get_temp_balance(from_address, currency))}")

            # if difference is higher than sent amount, do not send any taint
            sent_amount_blacklisted = amount_sent - difference
            if sent_amount_blacklisted > 0:
                transferred_amount = self.remove_from_blacklist(from_address, amount_sent, currency)
            else:
                self._logger.debug(self._tx_log + f"Tainted account {from_address} sent {amount_sent}, but taint value {self.format_exp(self.get_blacklist_value(from_address, currency))}" +
                                   f" is lower than temp balance after transaction ({self.format_exp(self.get_temp_balance(from_address, currency) - amount_sent)})")

        if self.is_blacklisted(to_address, currency) or transferred_amount > 0:
            self.add_to_blacklist(address=to_address, amount=transferred_amount, currency=currency_2, total_amount=amount_sent)

            if currency == currency_2 and transferred_amount > 0:
                self._logger.debug(self._tx_log + f"Transferred {self.format_exp(transferred_amount)} taint " +
                                   f"({self.format_exp(amount_sent)} total) of {currency} from {from_address} to {to_address}")

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
            self._logger.debug(
                self._tx_log + f"Fee: Removed {self.format_exp(tainted_fee)} wei taint from {sender}, and transferred {self.format_exp(tainted_fee_to_miner)} wei of which to miner {miner}")
