from typing import Optional

from policies.blacklist import FIFOBlacklist
from policies.blacklist_policy import BlacklistPolicy


class FIFOPolicy(BlacklistPolicy):
    """
    FIFO Policy.
    Keeps track of incoming transactions to tainted accounts and transfers taint in the order it was received.
    """

    def init_blacklist(self):
        return FIFOBlacklist()

    def get_policy_name(self):
        return "FIFO"

    def _transfer_taint(self, from_address, to_address: Optional[str], amount_sent, currency, currency_2: str = None) -> int:
        if currency_2 is None:
            currency_2 = currency

        transferred_amount = 0

        if self.is_permanently_tainted(from_address):
            transferred_amount = amount_sent

        elif self.is_blacklisted(from_address, currency):
            # amount by which the balance is higher than the value tracked by the blacklist
            untracked_balance = self._get_temp_balance(from_address, currency) - self._blacklist.get_tracked_value(from_address, currency)
            if untracked_balance < 0:
                self._logger.warning(self._tx_log + f"Tracked value {self._format_exp(self._blacklist.get_tracked_value(from_address, currency), 10)} for account {from_address} is higher than " +
                                     f"temp balance {self._format_exp(self._get_temp_balance(from_address, currency), 10)} (currency: {currency}); difference: " +
                                     f"{self._format_exp(self._blacklist.get_tracked_value(from_address, currency) - self._get_temp_balance(from_address, currency))}")

            # if difference is higher than sent amount, do not send any taint
            sent_amount_tracked = amount_sent - untracked_balance
            if sent_amount_tracked > 0:
                transferred_amount = self.remove_from_blacklist(from_address, sent_amount_tracked, currency)

        if (self.is_blacklisted(to_address, currency) or transferred_amount > 0) and to_address is not None:
            self.add_to_blacklist(address=to_address, amount=transferred_amount, currency=currency_2, total_amount=amount_sent)

            if currency == currency_2 and transferred_amount > 0:
                self._logger.debug(self._tx_log + f"Transferred {self._format_exp(transferred_amount)} taint " +
                                   f"({self._format_exp(amount_sent)} total) of {currency} from {from_address} to {to_address}")

        return transferred_amount

    def _process_gas_fees(self, transaction_log, transaction, full_block, sender):
        gas_price = transaction["gasPrice"]
        base_fee = full_block["baseFeePerGas"]
        gas_used = transaction_log["gasUsed"]
        miner = full_block["miner"]

        # return if neither sender nor miner are blacklisted
        if not (self.is_blacklisted(sender, "ETH") or self.is_blacklisted(miner, "ETH")):
            return

        total_fee_paid = gas_price * gas_used
        paid_to_miner = (gas_price - base_fee) * gas_used

        tainted_fee = 0

        # transfer taint for the part paid to the miner
        tainted_fee_to_miner = self._transfer_taint(from_address=sender, to_address=miner, amount_sent=paid_to_miner, currency="ETH")
        self._increase_temp_balance(miner, "ETH", paid_to_miner)
        self._reduce_temp_balance(sender, "ETH", paid_to_miner)

        # burn taint allocated to the burned part
        self._transfer_taint(from_address=sender, to_address=None, amount_sent=total_fee_paid - paid_to_miner, currency="ETH")
        self._reduce_temp_balance(sender, "ETH", total_fee_paid - paid_to_miner)

        if tainted_fee > 0:
            self._logger.debug(
                self._tx_log + f"Fee: Removed {self._format_exp(tainted_fee)} wei taint from {sender}, and transferred {self._format_exp(tainted_fee_to_miner)} wei of which to miner {miner}")
            self._record_tainted_transaction(sender, miner, fee=True)
