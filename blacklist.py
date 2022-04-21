from abc import ABC, abstractmethod

from typing import Set


class Blacklist(ABC):
    def __init__(self):
        self._blacklist = None

    @abstractmethod
    def add_to_blacklist(self, address: str, currency: str, amount: int, total_amount=None):
        """
        Adds the given address, currency and amount to the blacklist

        :param address: ethereum address
        :param currency: eth/token
        :param amount: amount to be added
        :param total_amount: total value of the (tainted) transaction - only needed for FIFO
        """
        pass

    @abstractmethod
    def is_blacklisted(self, address: str, currency=None) -> bool:
        """
        Checks if the given address and currency are on the blacklist

        :param address: ethereum address
        :param currency: token - optional, only checks account if not given
        :return: boolean
        """
        pass

    @abstractmethod
    def get_blacklisted_amount(self):
        """
        Retrieves the total blacklisted amount as a dict of currency: amount

        :return: total blacklisted currency
        """
        pass

    def get_blacklist(self):
        return self._blacklist

    @abstractmethod
    def remove_from_blacklist(self, address: str, amount: int, currency: str) -> int:
        """
        Reduce the blacklisted value of address and currency by amount

        :param address:
        :param amount: amount to be deducted
        :param currency: eth/token
        :return: the amount actually removed from the blacklist
        """
        pass

    @abstractmethod
    def add_account_to_blacklist(self, account: str, block: int):
        pass

    @abstractmethod
    def get_account_blacklist_value(self, account: str, currency: str) -> int:
        """
        Retrieves the amount of blacklisted currency for the given account and currency

        :param account: ethereum address
        :param currency: ETH or token address
        :return: the blacklisted value, 0 if not blacklisted
        """
        pass

    @abstractmethod
    def add_currency_to_all(self, account: str, currency: str):
        pass

    @abstractmethod
    def get_metrics(self):
        pass

    @abstractmethod
    def set_blacklist(self, blacklist):
        """
        Overwrite the blacklist

        :param blacklist: new blacklist
        """
        pass

    @abstractmethod
    def get_top_accounts(self, number, currencies: list) -> dict:
        """
        Get the top accounts by amount of tainted currencies

        :param currencies: currency/currencies to order the accounts by
        :param number: amount of accounts to return
        :return: dict of account: value
        """
        pass

    def get_tracked_value(self, account, currency):
        raise NotImplementedError("Only available for FIFO")
        pass


class SetBlacklist(Blacklist):

    def get_top_accounts(self, number, currencies) -> dict:
        pass

    def __init__(self):
        super().__init__()
        self._blacklist: Set = set()

    def set_blacklist(self, blacklist: list):
        self._blacklist = set(blacklist)

    def add_to_blacklist(self, address: str, currency: str, amount: int, total_amount=None):
        self._blacklist.add(address)

    def is_blacklisted(self, address: str, currency=None):
        return address in self._blacklist

    def get_blacklisted_amount(self):
        # blacklisted amounts for poison are calculated in the policy class, since balances need to be fetched
        pass

    def get_blacklist(self):
        return list(self._blacklist)

    def remove_from_blacklist(self, address: str, amount: int = None, currency: str = None):
        self._blacklist.remove(address)
        return -1

    def add_account_to_blacklist(self, account: str, block: int):
        self._blacklist.add(account)

    def get_account_blacklist_value(self, account: str, currency: int = None) -> int:
        return 0

    def add_currency_to_all(self, account: str, currency: str):
        pass

    def get_metrics(self):
        result = {"UniqueTaintedAccounts": len(self._blacklist)}

        return result


class DictBlacklist(Blacklist):
    def __init__(self):
        super().__init__()
        self._blacklist = {}

    def get_top_accounts(self, number, currencies) -> dict:
        all_accounts: dict = {}

        for account in self._blacklist:
            value = 0
            for currency in currencies:
                value += self.get_account_blacklist_value(account, currency)
            all_accounts[account] = value

        if len(all_accounts) < number:
            result_list = sorted(all_accounts, key=all_accounts.get)
        else:
            result_list = sorted(all_accounts, key=all_accounts.get)[-number:]

        return {account: all_accounts[account] for account in result_list}

    def set_blacklist(self, blacklist: dict):
        self._blacklist = blacklist

    def is_blacklisted(self, address: str, currency=None):
        if currency is None:
            return address in self._blacklist
        else:
            return address in self._blacklist and currency in self._blacklist[address]

    def add_to_blacklist(self, address, currency, amount, total_amount=None):
        # add address if not in blacklist
        if address not in self._blacklist:
            self._blacklist[address] = {}

        # add currency to address if not in blacklist
        if currency not in self._blacklist[address]:
            self._blacklist[address][currency] = 0

        self._blacklist[address][currency] += amount

    def remove_from_blacklist(self, address, amount, currency):
        amount = abs(amount)

        self._blacklist[address][currency] -= amount
        if self._blacklist[address][currency] == 0:
            del self._blacklist[address][currency]

            if not self._blacklist[address]:
                del self._blacklist[address]

        return amount

    def add_account_to_blacklist(self, account, block):
        # add address to blacklist
        if account not in self._blacklist:
            self._blacklist[account] = {}
        # set all flag or clear it
        self._blacklist[account]["all"] = []

    def get_account_blacklist_value(self, account: str, currency: str) -> int:
        if account not in self._blacklist or currency not in self._blacklist[account]:
            return 0

        else:
            return self._blacklist[account][currency]

    def add_currency_to_all(self, account: str, currency: str):
        self._blacklist[account]["all"].append(currency)

    def get_metrics(self):
        result = {}

        currencies = set()
        for account in self._blacklist:
            for currency in self._blacklist[account].keys():
                if currency != "all":
                    currencies.add(currency)

        result["UniqueCurrencies"] = len(currencies)
        result["Currencies"] = currencies

        result["UniqueTaintedAccounts"] = len(self._blacklist)

        return result

    def get_blacklisted_amount(self):
        amounts = {}

        for account in self._blacklist:
            for currency in self._blacklist[account].keys():
                if currency != "all":
                    if currency not in amounts:
                        amounts[currency] = self._blacklist[account][currency]
                    else:
                        amounts[currency] += self._blacklist[account][currency]

        return amounts


class FIFOBlacklist(Blacklist):
    def __init__(self):
        super(FIFOBlacklist, self).__init__()
        self._blacklist = {}

    def get_tracked_value(self, account, currency):
        tracked_value = 0
        if account not in self._blacklist or currency not in self._blacklist[account]:
            return tracked_value

        for tx in self._blacklist[account][currency]:
            tracked_value += tx[1]

        return tracked_value

    def get_top_accounts(self, number, currencies) -> dict:
        all_accounts: dict = {}

        for account in self._blacklist:
            value = 0
            for currency in currencies:
                value += self.get_account_blacklist_value(account, currency)
            all_accounts[account] = value

        if len(all_accounts) < number:
            result_list = sorted(all_accounts, key=all_accounts.get)
        else:
            result_list = sorted(all_accounts, key=all_accounts.get)[-number:]

        return {account: all_accounts[account] for account in result_list}

    def add_to_blacklist(self, address: str, currency: str, amount: int, total_amount=None):
        if total_amount is None:
            total_amount = amount

        # add address if not in blacklist
        if address not in self._blacklist:
            self._blacklist[address] = {}

        # add currency if not in blacklist[address]
        if currency not in self._blacklist[address]:
            self._blacklist[address][currency] = []

        if amount == 0 and self._blacklist[address][currency] and self._blacklist[address][currency][-1][0] == 0:
            self._blacklist[address][currency][-1][1] += total_amount
        else:
            self._blacklist[address][currency].append([amount, total_amount])

        # remove address and currency if value is 0
        if self.get_account_blacklist_value(address, currency) == 0:
            self._blacklist[address].pop(currency)
        if not self._blacklist[address]:
            self._blacklist.pop(address)

    def is_blacklisted(self, address: str, currency=None):
        if currency is None:
            return address in self._blacklist
        else:
            return address in self._blacklist and currency in self._blacklist[address]

    def get_blacklisted_amount(self):
        amounts = {}

        for address in self._blacklist:
            for currency in self._blacklist[address].keys():
                if currency != "all":
                    if currency not in amounts:
                        amounts[currency] = 0
                    for tx in self._blacklist[address][currency]:
                        amounts[currency] += tx[0]

        return amounts

    def remove_from_blacklist(self, address: str, amount: int, currency: str):
        """
        Removes amount from the blacklisted account's previous transactions

        :param address: ethereum address
        :param amount: amount to remove
        :param currency: eth/token
        :return: the amount of removed value that was blacklisted
        """
        blacklisted_amount_removed = 0

        while self._blacklist[address][currency]:
            blacklisted_tx = self._blacklist[address][currency][0]
            amount_reduced = min(amount, blacklisted_tx[1])
            remaining_taint_in_tx = min(blacklisted_tx[0], blacklisted_tx[1] - amount_reduced)
            removed_taint = blacklisted_tx[0] - remaining_taint_in_tx
            blacklisted_amount_removed += removed_taint

            self._blacklist[address][currency][0][0] -= removed_taint
            self._blacklist[address][currency][0][1] -= amount_reduced

            # remove the transaction if all its value has been used
            if self._blacklist[address][currency][0][1] == 0:
                self._blacklist[address][currency].pop(0)

            amount -= amount_reduced
            if amount == 0:
                break

        if self.get_account_blacklist_value(address, currency) == 0:
            self._blacklist[address].pop(currency)
        if not self._blacklist[address]:
            self._blacklist.pop(address)
        return blacklisted_amount_removed

    def add_account_to_blacklist(self, account: str, block: int):
        if account not in self._blacklist:
            self._blacklist[account] = {}
        # set all flag or clear it
        self._blacklist[account]["all"] = []

    def get_account_blacklist_value(self, account: str, currency: str):
        blacklisted_value = 0
        if account not in self._blacklist or currency not in self._blacklist[account]:
            return blacklisted_value

        if currency == "all":
            return self._blacklist[account][currency]

        for tx in self._blacklist[account][currency]:
            blacklisted_value += tx[0]

        return blacklisted_value

    def add_currency_to_all(self, account: str, currency: str):
        self._blacklist[account]["all"].append(currency)

    def get_metrics(self):
        result = {}

        currencies = set()
        for account in self._blacklist:
            for currency in self._blacklist[account].keys():
                if currency != "all":
                    currencies.add(currency)

        result["UniqueCurrencies"] = len(currencies)
        result["Currencies"] = currencies

        result["UniqueTaintedAccounts"] = len(self._blacklist)

        return result

    def set_blacklist(self, blacklist: dict):
        self._blacklist = blacklist
