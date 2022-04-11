from blacklist import DictBlacklist
from blacklist_policy import BlacklistPolicy


class HaircutPolicy(BlacklistPolicy):
    def init_blacklist(self):
        return DictBlacklist()

    def transfer_taint(self, from_address, to_address, amount_sent, currency, currency_2=None) -> int:
        if currency_2 is None:
            currency_2 = currency

        blacklist_value = self.get_blacklist_value(from_address, currency)
        sender_balance = self.get_temp_balance(from_address, currency)

        if sender_balance == 0:
            taint_proportion = 1
        else:
            taint_proportion = blacklist_value / sender_balance

        transferred_amount = int(amount_sent * taint_proportion)

        if transferred_amount == 0:
            return 0

        self.remove_from_blacklist(from_address, transferred_amount, currency)

        if to_address is None or to_address == self._eth_utils.null_address:
            self._logger.info(self._tx_log + f"{amount_sent} tokens were burned, of which {transferred_amount} were blacklisted.")
            return transferred_amount

        self.add_to_blacklist(to_address, transferred_amount, currency_2)

        if currency == currency_2:
            self._logger.debug(self._tx_log + f"Transferred {format(transferred_amount, '.2e')} taint of {currency} from {from_address} to {to_address}. Taint proportion was {taint_proportion*100}%")

        return transferred_amount

    def check_gas_fees(self, transaction_log, transaction, full_block, sender):
        gas_price = transaction["gasPrice"]
        base_fee = full_block["baseFeePerGas"]
        gas_used = transaction_log["gasUsed"]
        miner = full_block["miner"]

        total_fee_paid = gas_price * gas_used
        paid_to_miner = (gas_price - base_fee) * gas_used

        blacklist_value = self.get_blacklist_value(sender, "ETH")
        sender_balance = self.get_temp_balance(sender, "ETH")

        taint_proportion = blacklist_value / sender_balance

        tainted_fee = int(total_fee_paid * taint_proportion)
        tainted_fee_to_miner = int(paid_to_miner * taint_proportion)

        self.reduce_temp_balance(sender, "ETH", total_fee_paid)
        self.increase_temp_balance(miner, "ETH", paid_to_miner)

        if tainted_fee == 0:
            return

        self.remove_from_blacklist(sender, tainted_fee, "ETH")
        self.add_to_blacklist(miner, tainted_fee_to_miner, "ETH")

        self._logger.debug(self._tx_log + f"Fee: Removed {format(tainted_fee, '.2e')} wei taint from {sender}, transferred {format(tainted_fee_to_miner, '.2e')} " +
                           f"to miner {miner} and burned {format(tainted_fee - tainted_fee_to_miner, '.2e')}, taint proportion was {taint_proportion*100}%")
