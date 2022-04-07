from abc import ABC, abstractmethod


class Blacklist(ABC):
    @abstractmethod
    def add_to_blacklist(self, address: str, currency: str, amount: int, immediately=False):
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
    def remove_from_blacklist(self, address: str, amount: int, currency: str, immediately=False):
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


class DictBlacklist(Blacklist):
    def __init__(self):
        self._blacklist = {}
        """ Dictionary of blacklisted accounts, with a sub-dictionary of the blacklisted currencies of these accounts """

    def add_to_blacklist(self, address: str, currency: str, amount: int, immediately=False):
        # add address if not in blacklist
        if address not in self._blacklist:
            self._blacklist[address] = {}

        # add currency to address if not in blacklist
        if currency not in self._blacklist[address]:
            self._blacklist[address][currency] = 0

        self._blacklist[address][currency] += amount

    def is_blacklisted(self, address: str, currency=None):
        if currency is None:
            return address in self._blacklist
        else:
            return address in self._blacklist and currency in self._blacklist[address]

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

    def get_blacklist(self):
        return self._blacklist

    def remove_from_blacklist(self, address: str, amount: int, currency: str, immediately=False):
        amount = abs(amount)

        self._blacklist[address][currency] -= amount
        if self._blacklist[address][currency] == 0:
            del self._blacklist[address]

            if not self._blacklist[address]:
                del self._blacklist[address]

    def add_account_to_blacklist(self, account: str, block: int):
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


class BufferedDictBlacklist(DictBlacklist):
    def __init__(self):
        super().__init__()
        self._write_queue = []

    def _queue_write(self, account, currency, amount):
        self._write_queue.append([account, currency, amount])

    def add_to_blacklist(self, address, currency, amount, immediately=False):
        # add address if not in blacklist
        if address not in self._blacklist:
            self._blacklist[address] = {}

        # add currency to address if not in blacklist
        if currency not in self._blacklist[address]:
            self._blacklist[address][currency] = 0

        if immediately:
            self._blacklist[address][currency] += amount
        else:
            self._queue_write(address, currency, amount)

    def get_blacklist(self):
        if self._write_queue:
            self.write_blacklist()
        return self._blacklist

    def write_blacklist(self):
        for operation in self._write_queue:
            account = operation[0]
            currency = operation[1]
            amount = operation[2]

            if account not in self._blacklist:
                self._blacklist[account] = {}
            if currency not in self._blacklist[account]:
                self._blacklist[account][currency] = 0

            self._blacklist[account][currency] += amount

            # delete currency from dict if 0
            if self._blacklist[account][currency] <= 0:
                del self._blacklist[account][currency]

                # delete account from dict if no currencies left
                if not self._blacklist[account]:
                    del self._blacklist[account]

        self._write_queue = []

    def remove_from_blacklist(self, address, amount, currency, immediately=False):
        amount = abs(amount)

        if immediately:
            super().remove_from_blacklist(address, amount, currency)
        else:
            self._queue_write(address, currency, -amount)

    def add_account_to_blacklist(self, account, block):
        # finish all pending write operations; WARNING: will cause issues if done mid-block
        self.write_blacklist()

        super().add_account_to_blacklist(account, block)
