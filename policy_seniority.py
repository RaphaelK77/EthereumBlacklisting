import logging

from typing import Union
from web3 import Web3

from blacklist import BufferedDictBlacklist
from blacklist_policy import BlacklistPolicy

delayed_write = False


class SeniorityPolicy(BlacklistPolicy):
    def __init__(self, w3: Web3, checkpoint_file, logging_level=logging.INFO, log_to_file=False, log_to_db=False, buffered=False):
        super().__init__(w3, checkpoint_file, BufferedDictBlacklist(), logging_level=logging_level, log_to_file=log_to_file, log_to_db=log_to_db)
        self._buffered = buffered

    def transfer_taint(self, from_address, to_address, amount_sent, currency):
        transferred_amount = min(amount_sent, self.get_blacklist_value(from_address, currency))

        self.remove_from_blacklist(from_address, transferred_amount, currency)
        if to_address is None or to_address == self._eth_utils.null_address:
            self._logger.info(self._tx_log + f"{amount_sent} tokens were burned, of which {transferred_amount} were blacklisted.")
            return

        self.add_to_blacklist(to_address, transferred_amount, currency)

        self._logger.debug(self._tx_log + f"Transferred {format(transferred_amount, '.2e')} taint of {currency} from {from_address} to {to_address}")
        self.save_log("DEBUG", "TRANSFER", from_address, to_address, transferred_amount, currency)

    def add_to_blacklist(self, address: str, amount: int, currency: str, immediately=False):
        super().add_to_blacklist(address, amount=amount, currency=currency, immediately=not self._buffered)

    def remove_from_blacklist(self, address: str, amount: Union[int, float], currency: str, immediately=False):
        super().remove_from_blacklist(address, amount, currency, immediately=not self._buffered)

    def process_event(self, event):
        if "logIndex" in event:
            info = f"(Transfer, index {event['logIndex']})"
        else:
            info = "(Internal Tx)"

        if event["event"] == "Deposit":
            dst = event["args"]["dst"]
            value = event["args"]["wad"]
            if not self._eth_utils.is_weth(event["address"]):
                return True

            self.add_to_temp_balances(dst, "ETH")
            self.add_to_temp_balances(dst, self._eth_utils.WETH)
            #
            # if value > self.temp_balances[dst]["ETH"]:
            #     self._logger.warning(self._tx_log + f"Not enough balance ({format(self.temp_balances[dst]['ETH'], '.2e')} ETH) for {dst} " +
            #                        f"to deposit {format(value, '.2e')} ETH. Executing next internal transfer. {info}")
            #     return False
            #
            # self.temp_balances[dst]["ETH"] -= value
            # self.temp_balances[dst][self._eth_utils.WETH] += value

            if self.is_blacklisted(dst, "ETH"):
                transferred_amount = min(self.get_blacklist_value(dst, "ETH"), value)
                self.remove_from_blacklist(dst, transferred_amount, "ETH")
                self.add_to_blacklist(dst, transferred_amount, self._eth_utils.WETH)

            self._logger.debug(self._tx_log + f"Processed Deposit. Converted {format(value, '.2e')} ETH of {dst} to WETH.")
        elif event["event"] == "Withdrawal":
            src = event["args"]["src"]
            value = event["args"]["wad"]
            if not self._eth_utils.is_weth(event["address"]):
                return True

            self.add_to_temp_balances(src, "ETH")
            self.add_to_temp_balances(src, self._eth_utils.WETH)
            #
            # if value > self.temp_balances[src][self._eth_utils.WETH]:
            #     self._logger.warning(self._tx_log + f"Not enough balance ({format(self.temp_balances[src]['ETH'], '.2e')} WETH) for {src}" +
            #                        f" to withdraw {format(value, '.2e')} WETH. Executing next internal transfer. {info}")
            #     return False
            #
            # self.temp_balances[src]["ETH"] += value
            # self.temp_balances[src][self._eth_utils.WETH] -= value

            if self.is_blacklisted(src, self._eth_utils.WETH):
                transferred_amount = min(self.get_blacklist_value(src, self._eth_utils.WETH), value)
                self.remove_from_blacklist(src, transferred_amount, self._eth_utils.WETH)
                self.add_to_blacklist(src, transferred_amount, "ETH")

            self._logger.debug(self._tx_log + f"Processed Withdrawal. Converted {format(value, '.2e')} WETH of {src} to ETH.")
        # Transfer event, incl. internal transactions
        else:
            currency = event["address"]
            if currency != "ETH":
                currency = Web3.toChecksumAddress(currency)
            transfer_sender = event['args']['from']
            transfer_receiver = event['args']['to']
            amount = event['args']['value']

            for account in transfer_sender, transfer_receiver:
                # skip null address
                if account == self._eth_utils.null_address:
                    continue

                if currency != "ETH" and self.is_blacklisted(address=account, currency="all"):
                    self.fully_taint_token(account, currency)

                # self.add_to_temp_balances(account, currency)

            # if the sender is blacklisted, transfer taint to receiver
            if self.is_blacklisted(transfer_sender, currency):
                self.transfer_taint(transfer_sender, transfer_receiver, amount, currency)

            # update balances
            # if transfer_sender != self._eth_utils.null_address:
            #     self.temp_balances[transfer_sender][currency] -= amount
            # if transfer_receiver != self._eth_utils.null_address:
            #     self.temp_balances[transfer_receiver][currency] += amount

            # self._logger.debug(self._tx_log + f"Transferred {format(amount, '.2e')} temp balance of {currency} from {transfer_sender} to {transfer_receiver} " + info)

        return True

    def add_to_temp_blacklist(self, account, currency):
        if account not in self.temp_blacklist:
            self.temp_blacklist[account] = {}
        if currency not in self.temp_blacklist[account]:
            self.temp_blacklist[account][currency] = self.get_blacklist_value(account, currency)

    def check_gas_fees(self, transaction_log, transaction, full_block, sender):
        gas_price = transaction["gasPrice"]
        base_fee = full_block["baseFeePerGas"]
        gas_used = transaction_log["gasUsed"]
        miner = full_block["miner"]

        total_fee_paid = gas_price * gas_used
        paid_to_miner = (gas_price - base_fee) * gas_used

        tainted_fee = min(total_fee_paid, self.get_blacklist_value(sender, "ETH"))
        tainted_fee_to_miner = min(paid_to_miner, self.get_blacklist_value(sender, "ETH"))

        self.remove_from_blacklist(sender, tainted_fee, "ETH")
        self.add_to_blacklist(miner, tainted_fee_to_miner, "ETH")

        # self.add_to_temp_balances(sender, "ETH")
        # self.temp_balances[sender]["ETH"] -= total_fee_paid
        # self.add_to_temp_balances(miner, "ETH")
        # self.temp_balances[miner]["ETH"] += paid_to_miner

        self._logger.debug(self._tx_log + f"Fee: Removed {format(tainted_fee, '.2e')} wei taint from {sender}, and transferred {format(tainted_fee_to_miner, '.2e')} wei of which to miner {miner}")

    def temp_transfer(self, temp_blacklist, sender, receiver, currency, amount):
        """
        Taint transfer on temp blacklist - only needed if buffering is enabled

        :param temp_blacklist: temporary blacklist dict
        :param sender: account
        :param receiver: account
        :param currency: token
        :param amount: total amount sent
        :return: updated temp blacklist
        """
        if sender in temp_blacklist and currency in temp_blacklist[sender] and temp_blacklist[sender][currency] > 0:
            transferred_amount = min(amount, temp_blacklist[sender][currency])

            temp_blacklist[sender][currency] -= transferred_amount

            if receiver == self._eth_utils.null_address:
                self._logger.info(self._tx_log + f"{amount} tokens were burned, of which {transferred_amount} were blacklisted.")
                return

            temp_blacklist[receiver][currency] += transferred_amount

        return temp_blacklist

    def sanity_check(self):
        full_blacklist = self.get_blacklist()

        if self.is_blacklisted(self._eth_utils.null_address):
            self._logger.warning(f"Null address is blacklisted. Values: {full_blacklist[self._eth_utils.null_address]}")
        for account in full_blacklist:
            for currency in full_blacklist[account]:
                if currency == "all":
                    continue
                blacklist_value = full_blacklist[account][currency]
                balance = self.get_balance(account, currency, self._current_block + 1)
                if blacklist_value > balance:
                    self._logger.warning(f"Blacklist value {format(blacklist_value, '.2e')} for account {account} and currency {currency} is greater than balance {format(balance, '.2e')}")

    def increase_temp_balance(self, account, currency, amount):
        # overwrite unnecessary function
        pass

    def reduce_temp_balance(self, account, currency, amount):
        # overwrite unnecessary function
        pass

    def add_to_temp_balances(self, account, currency):
        # overwrite unnecessary function
        pass
