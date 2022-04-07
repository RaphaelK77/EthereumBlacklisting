from blacklist_policy import BlacklistPolicy


class SeniorityPolicy(BlacklistPolicy):
    def check_transaction(self, transaction_log, transaction, full_block, internal_transactions):
        pass
