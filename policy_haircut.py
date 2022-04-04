import logging
from typing import Union

from web3 import Web3

from blacklist_policy import BlacklistPolicy
from ethereum_utils import EthereumUtils


class HaircutPolicy(BlacklistPolicy):

    def __init__(self, w3: Web3, logging_level=logging.INFO):
        super().__init__(w3, logging_level)
        self._eth_utils = EthereumUtils(w3)
        self._current_block = -1
        self._tx_log = ""

    def check_transaction(self, transaction_log, transaction, full_block):
        sender = transaction["from"]
        receiver = transaction["to"]

        if transaction["blockNumber"] > self._current_block >= 0:
            self._logger.debug(f"Writing changes, since transaction block {transaction['blockNumber']} > current block {self._current_block}.")
            # write changes queued up in the last block
            self.write_blacklist()
        self._current_block = transaction["blockNumber"]

        self._tx_log = f"Transaction {transaction['hash'].hex()} | "

        # if any of the sender's ETH is blacklisted, check if any ETH was transferred
        if sender in self._blacklist and "ETH" in self._blacklist[sender] and transaction["value"] > 0:
            # transfer taint from sender to receiver (no need to check for "all", since ETH is tainted immediately)
            self.transfer_taint(from_address=sender, to_address=receiver, amount_sent=transaction["value"], currency="ETH")

        # if the tx was a smart contract invocation
        if transaction_log["logs"]:
            # get all transfers
            transfer_events = self._eth_utils.get_all_events_of_type_in_tx(transaction_log, ["Transfer"])

            # dicts to store a local balance and the temporary blacklisting status while processing the transaction logs
            temp_balances = {}
            temp_blacklist = {}

            for transfer_event in transfer_events:
                currency = transfer_event["address"]
                transfer_sender = transfer_event['args']['from']
                transfer_receiver = transfer_event['args']['to']
                amount = transfer_event['args']['value']

                if self._eth_utils.is_eth(currency):
                    currency = "ETH"

                for account in transfer_sender, transfer_receiver:
                    # check if "all" flag is set for either sender or receiver, taint all tokens if necessary
                    if currency != "ETH" and self.is_blacklisted(address=account, currency="all"):
                        # taint entire balance of this token if not
                        if currency not in self._blacklist[account]["all"]:
                            entire_balance = self._eth_utils.get_token_balance(account, currency, self._current_block)
                            self.add_to_blacklist(address=account, amount=entire_balance, currency=currency, immediately=True)
                            # add token to "all"-list to mark it as done
                            self._blacklist[account]["all"].append(currency)
                            self._logger.info(self._tx_log + f"Tainted entire balance ({format(entire_balance, '.2e')}) of token {currency} for account {account}.")

                    # add the account to temp balances
                    if account not in temp_balances:
                        temp_balances[account] = {}
                    if currency not in temp_balances[account]:
                        temp_balances[account][currency] = self._eth_utils.get_balance(account, currency, self._current_block)

                    # add the account to the temp blacklist if it is on the full blacklist
                    if self.is_blacklisted(account):
                        if account not in temp_blacklist:
                            temp_blacklist[account] = {}
                        if currency not in temp_blacklist[account] and self.is_blacklisted(address=account, currency=currency):
                            temp_blacklist[account][currency] = self._blacklist[account][currency]

                # update temp blacklist with the current transfer
                temp_blacklist = self.temp_transfer(temp_balances, temp_blacklist, transfer_sender, transfer_receiver, currency, amount)

                # update temp balances with the amount sent in the current transfer
                temp_balances[transfer_sender][currency] -= amount
                temp_balances[transfer_receiver][currency] += amount

            # once the transfer has been processed, execute all resulting changes
            for account in temp_blacklist:
                for currency in temp_blacklist[account]:
                    if account in self._blacklist and currency in self._blacklist[account]:
                        difference = temp_blacklist[account][currency] - self._blacklist[account][currency]
                        if difference:
                            self._queue_write(account, currency, difference)
                    else:
                        self._queue_write(account, currency, temp_blacklist[account][currency])

        # if the sender has any blacklisted ETH, taint the paid gas fees
        if self.is_blacklisted(sender, "ETH"):
            self.check_gas_fees(transaction_log, transaction, full_block, sender)

    def check_gas_fees(self, transaction_log, transaction, block, sender):
        gas_price = transaction["gasPrice"]
        base_fee = block["baseFeePerGas"]
        gas_used = transaction_log["gasUsed"]
        miner = block["miner"]

        total_fee_paid = gas_price * gas_used
        paid_to_miner = (gas_price - base_fee) * gas_used
        proportion_paid_to_miner = paid_to_miner / total_fee_paid

        taint_proportion = self._blacklist[sender]["ETH"] / self._eth_utils.get_balance(sender, "ETH", self._current_block)
        tainted_fee = total_fee_paid * taint_proportion
        tainted_fee_to_miner = tainted_fee * proportion_paid_to_miner

        self.remove_from_blacklist(sender, amount=tainted_fee, currency="ETH")
        self.add_to_blacklist(miner, amount=tainted_fee_to_miner, currency="ETH")

        self._logger.debug(self._tx_log + f"Fee: Removed {format(tainted_fee, '.2e')} wei taint from {sender}, and transferred {format(tainted_fee_to_miner, '.2e')} wei of which to miner {miner}")

    def temp_transfer(self, temp_balances, temp_blacklist, sender, receiver, currency, amount):
        """
        Transfer taint from sender to receiver on the temporary blacklist

        :param temp_balances: dict of locally saved temp balances
        :param temp_blacklist: dict of temporary blacklist
        :param sender: transaction sender
        :param receiver: transaction receiver
        :param currency: Ethereum token address
        :param amount: total amount sent
        :return: updated temp_blacklist
        """
        # if the sender or currency are not blacklisted, nothing happens
        # this assumes the logs are checked in the correct order
        if sender in temp_blacklist and currency in temp_blacklist[sender]:
            taint_proportion = temp_blacklist[sender][currency] / temp_balances[sender][currency]
            transferred_amount = amount * taint_proportion
            temp_blacklist[sender][currency] -= transferred_amount
            if receiver not in temp_blacklist:
                temp_blacklist[receiver] = {currency: transferred_amount}
            elif currency not in temp_blacklist[receiver]:
                temp_blacklist[receiver][currency] = transferred_amount
            else:
                temp_blacklist[receiver][currency] += transferred_amount

        return temp_blacklist

    def transfer_taint(self, from_address: str, to_address: str, amount_sent: int, currency: str):
        # check if ETH or WETH, then calculate the amount that should be tainted
        balance = self._eth_utils.get_balance(from_address, currency, self._current_block)
        if balance == 0:
            self._logger.error(self._tx_log + "Balance is 0")
            exit(-1)
        taint_proportion = self._blacklist[from_address][currency] / balance

        transferred_amount = amount_sent * taint_proportion
        self.remove_from_blacklist(address=from_address, amount=transferred_amount, currency=currency)
        self.add_to_blacklist(address=to_address, amount=transferred_amount, currency=currency)

        self._logger.debug(self._tx_log + f"Transferred {format(transferred_amount, '.2e')} taint of {currency} from {from_address} to {to_address}")
        self._logger.debug(self._tx_log + f"Taint proportion was {format(taint_proportion * 100, '.5f')}% of the sent amount {format(amount_sent, '.2e')}, with a balance of {format(balance, '.2e')}")

    def add_account_to_blacklist(self, address: str, block: int):
        """
        Add an entire account to the blacklist.
        The account dict will hold under "all" every currency already tainted.

        :param address: Ethereum address to blacklist
        :param block: block at which the current balance should be blacklisted
        """
        # finish all pending write operations; WARNING: will cause issues if done mid-block
        self.write_blacklist()

        # add address to blacklist
        if address not in self._blacklist:
            self._blacklist[address] = {}
        # set all flag or clear it
        self._blacklist[address]["all"] = []

        # blacklist all ETH
        eth_balance = self._eth_utils.get_balance(account=address, currency="ETH", block=block)
        self._blacklist[address]["ETH"] = eth_balance

        self._logger.info(f"Blacklisted entire balance of {format(eth_balance, '.2e')} wei (ETH) of account {address}")

    def get_blacklisted_amount(self, block=None):
        amounts = {}

        for account in self._blacklist:
            for currency in self._blacklist[account].keys():
                if currency != "all":
                    if currency not in amounts:
                        amounts[currency] = self._blacklist[account][currency]
                    else:
                        amounts[currency] += self._blacklist[account][currency]

        return amounts

    def get_blacklist_metrics(self):
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
