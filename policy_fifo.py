from blacklist_policy import BlacklistPolicy


class FIFOPolicy(BlacklistPolicy):
    def init_blacklist(self):
        pass

    def transfer_taint(self, from_address, to_address, amount_sent, currency, currency_2=None) -> int:
        pass

    def check_gas_fees(self, transaction_log, transaction, full_block, sender):
        pass
