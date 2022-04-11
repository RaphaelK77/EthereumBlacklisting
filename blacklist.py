from abc import ABC, abstractmethod


class Blacklist(ABC):
    @abstractmethod
    def add_to_blacklist(self, address: str, currency: str, amount: int):
        pass

    @abstractmethod
    def is_blacklisted(self, address: str, currency=None):
        pass

    @abstractmethod
    def get_blacklisted_amount(self):
        pass

    @abstractmethod
    def get_blacklist(self):
        pass

    @abstractmethod
    def remove_from_blacklist(self, address: str, amount: int, currency: str):
        pass

    @abstractmethod
    def add_account_to_blacklist(self, account: str, block: int):
        pass

    @abstractmethod
    def get_account_blacklist_value(self, account: str, currency: int):
        pass

    @abstractmethod
    def add_currency_to_all(self, account: str, currency: str):
        pass

    @abstractmethod
    def get_metrics(self):
        pass

    def write_blacklist(self):
        pass

    @abstractmethod
    def set_blacklist(self, blacklist):
        pass


class DictBlacklist(Blacklist):
    def __init__(self):
        self._blacklist = {}

    def set_blacklist(self, blacklist: dict):
        self._blacklist = blacklist

    def is_blacklisted(self, address: str, currency=None):
        if currency is None:
            return address in self._blacklist
        else:
            return address in self._blacklist and currency in self._blacklist[address]

    def add_to_blacklist(self, address, currency, amount):
        # add address if not in blacklist
        if address not in self._blacklist:
            self._blacklist[address] = {}

        # add currency to address if not in blacklist
        if currency not in self._blacklist[address]:
            self._blacklist[address][currency] = 0

        self._blacklist[address][currency] += amount

    def get_blacklist(self):
        return self._blacklist

    def remove_from_blacklist(self, address, amount, currency):
        amount = abs(amount)

        self._blacklist[address][currency] -= amount
        if self._blacklist[address][currency] == 0:
            del self._blacklist[address][currency]

            if not self._blacklist[address]:
                del self._blacklist[address]

    def add_account_to_blacklist(self, account, block):
        # finish all pending write operations; WARNING: will cause issues if done mid-block
        self.write_blacklist()

        # add address to blacklist
        if account not in self._blacklist:
            self._blacklist[account] = {}
        # set all flag or clear it
        self._blacklist[account]["all"] = []

    def get_account_blacklist_value(self, account: str, currency: int):
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
