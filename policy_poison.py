from blacklist import SetBlacklist
from blacklist_policy import BlacklistPolicy


class PoisonPolicy(BlacklistPolicy):
    """
    Poison policy.
    Keeps a list of fully tainted accounts and taints every account that receives a transaction from a tainted account.
    """

    def init_blacklist(self):
        return SetBlacklist()

    def get_policy_name(self):
        return "Poison"

    def _transfer_taint(self, from_address, to_address, amount_sent, currency, currency_2=None) -> int:
        if not self.is_blacklisted(from_address, currency):
            return 0

        self.add_to_blacklist(to_address, self._current_block, currency="")
        return 1

    def _process_gas_fees(self, transaction_log, transaction, full_block, sender):
        if not self.is_blacklisted(sender, "ETH"):
            return

        miner = full_block["miner"]

        self.add_to_blacklist(miner, self._current_block, currency="")

    def get_blacklisted_amount(self) -> dict:
        blacklist = self._blacklist.get_blacklist()
        amounts = {"ETH": 0, self._eth_utils.WETH: 0}

        for account in blacklist:
            amounts["ETH"] += self._get_balance(account, "ETH", self._current_block + 1)
            amounts[self._eth_utils.WETH] += self._get_balance(account, self._eth_utils.WETH, self._current_block + 1)

        return amounts

    def _increase_temp_balance(self, account, currency, amount):
        # overwrite unnecessary function
        pass

    def _reduce_temp_balance(self, account, currency, amount):
        # overwrite unnecessary function
        pass

    def _add_to_temp_balances(self, account, currency, get_balance=False):
        # overwrite unnecessary function
        pass

    def fully_taint_token(self, account, currency, overwrite=False, block=None):
        # overwrite unnecessary function
        pass

    def sanity_check(self):
        if self.is_blacklisted(self._eth_utils.null_address):
            self._logger.warning("Null address is blacklisted.")

    def _get_temp_balance(self, account, currency) -> int:
        # overwrite unnecessary function
        pass
