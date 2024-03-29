from policies.blacklist import DictBlacklist
from policies.blacklist_policy import BlacklistPolicy


class ReversedSeniorityPolicy(BlacklistPolicy):
    """
    Reversed seniority policy.
    Taint is transferred in a last-out fashion.
    """

    def init_blacklist(self):
        return DictBlacklist()

    def get_policy_name(self):
        return "Reversed Seniority"

    def _transfer_taint(self, from_address, to_address, amount_sent, currency, currency_2=None) -> int:
        if not self.is_blacklisted(from_address, currency):
            return 0

        if currency_2 is None:
            currency_2 = currency

        if self.is_permanently_tainted(from_address):
            transferred_amount = amount_sent
        else:
            blacklist_value = self.get_blacklist_value(from_address, currency)
            sender_balance = self._get_temp_balance(from_address, currency)
            transferred_amount = max(0, blacklist_value - (sender_balance - amount_sent))

            if transferred_amount == 0:
                return 0

            self.remove_from_blacklist(from_address, transferred_amount, currency)

        if to_address is None or to_address == self._eth_utils.null_address:
            self._logger.info(self._tx_log + f"{amount_sent} tokens were burned, of which {transferred_amount} were blacklisted.")
            return transferred_amount

        self.add_to_blacklist(to_address, transferred_amount, currency_2)

        if currency == currency_2:
            self._logger.debug(self._tx_log + f"Transferred {format(transferred_amount, '.2e')} taint of {currency} from {from_address} to {to_address}")

        return transferred_amount

    def _process_gas_fees(self, transaction_log, transaction, full_block, sender):
        if not self.is_blacklisted(sender, "ETH"):
            return

        gas_price = transaction["gasPrice"]
        base_fee = full_block["baseFeePerGas"]
        gas_used = transaction_log["gasUsed"]
        miner = full_block["miner"]

        total_fee_paid = gas_price * gas_used
        paid_to_miner = (gas_price - base_fee) * gas_used

        if self.is_permanently_tainted(sender):
            tainted_fee = total_fee_paid
            tainted_fee_to_miner = paid_to_miner
        else:
            blacklist_value = self.get_blacklist_value(sender, "ETH")
            sender_balance = self._get_temp_balance(sender, "ETH")

            tainted_fee = max(0, blacklist_value - (sender_balance - total_fee_paid))
            tainted_fee_to_miner = min(paid_to_miner, tainted_fee)

        self._reduce_temp_balance(sender, "ETH", total_fee_paid)
        self._increase_temp_balance(miner, "ETH", paid_to_miner)

        if tainted_fee == 0:
            return

        self.remove_from_blacklist(sender, tainted_fee, "ETH")
        self.add_to_blacklist(miner, tainted_fee_to_miner, "ETH")

        self._record_tainted_transaction(sender, miner, fee=True)

        self._logger.debug(self._tx_log + f"Fee: Removed {format(tainted_fee, '.2e')} wei taint from {sender}, transferred {format(tainted_fee_to_miner, '.2e')} " +
                           f"to miner {miner} and burned {format(tainted_fee - tainted_fee_to_miner, '.2e')}")
