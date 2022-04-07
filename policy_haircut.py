import json
import logging

from web3 import Web3

from blacklist import BufferedDictBlacklist
from blacklist_policy import BlacklistPolicy

null_address = "0x0000000000000000000000000000000000000000"


class HaircutPolicy(BlacklistPolicy):

    def __init__(self, w3: Web3, checkpoint_file, logging_level=logging.INFO, log_to_file=False):
        super().__init__(w3, blacklist=BufferedDictBlacklist(), checkpoint_file=checkpoint_file, logging_level=logging_level, log_to_file=log_to_file)

    def export_blacklist(self, target_file):
        with open(target_file, "w") as outfile:
            json.dump(self._blacklist.get_blacklist(), outfile)

        self._logger.info(f"Successfully exported blacklist to {target_file}.")

    def check_transaction(self, transaction_log, transaction, full_block, internal_transactions):
        sender = transaction["from"]
        receiver = transaction["to"]

        # write changes queued up in the last block
        if transaction["blockNumber"] > self._current_block >= 0:
            self._logger.debug(f"Writing changes, since transaction block {transaction['blockNumber']} > current block {self._current_block}...")
            self._blacklist.write_blacklist()
        self._current_block = transaction["blockNumber"]

        self._tx_log = f"Transaction https://etherscan.io/tx/{transaction['hash'].hex()} | "

        # if the sender has any blacklisted ETH, taint the paid gas fees
        if self.is_blacklisted(sender, "ETH"):
            self.check_gas_fees(transaction_log, transaction, full_block, sender)

        # do not process wrap/unwrap transactions
        if self._eth_utils.is_eth(receiver):
            return

        # skip the remaining code if there were no smart contract events
        if not transaction_log["logs"]:
            # if any of the sender's ETH is blacklisted, taint any sent ETH
            # (this will be done as part of the transfers if the tx is a smart contract invocation)
            if transaction["value"] > 0 and self.is_blacklisted(sender, "ETH"):
                # transfer taint from sender to receiver (no need to check for "all", since ETH is tainted immediately)
                self.transfer_taint(from_address=sender, to_address=receiver, amount_sent=transaction["value"], currency="ETH")
            return

        # get all transfers
        transfer_events = self._eth_utils.get_all_events_of_type_in_tx(transaction_log, ["Transfer"])

        # get all internal transactions
        transfer_events += internal_transactions

        # dicts to store a local balance and the temporary blacklisting status while processing the transaction logs
        temp_balances = {}
        temp_blacklist = {}

        # if ETH is transferred with the transaction, adjust temporary balances and blacklist accordingly
        if transaction["value"] > 0:
            for account in sender, receiver:
                temp_balances[account] = {}
                temp_balances[account]["ETH"] = self.get_balance(account, "ETH", self._current_block)

                if self.is_blacklisted(address=account, currency="ETH"):
                    temp_blacklist[account] = {"ETH": self.get_blacklist_value(account, "ETH")}

            # update temp blacklist
            temp_blacklist = self.temp_transfer(temp_balances, temp_blacklist, sender, receiver, "ETH", transaction["value"])

            # update temp balances
            temp_balances[sender]["ETH"] -= transaction["value"]
            temp_balances[receiver]["ETH"] += transaction["value"]

        for transfer_event in transfer_events:
            currency = transfer_event["address"]
            transfer_sender = transfer_event['args']['from']
            transfer_receiver = transfer_event['args']['to']
            amount = transfer_event['args']['value']

            if self._eth_utils.is_eth(currency):
                currency = "ETH"

            for account in transfer_sender, transfer_receiver:
                # skip null address
                if account == null_address:
                    continue

                # check if "all" flag is set for either sender or receiver, taint all tokens if necessary
                if currency != "ETH" and self.is_blacklisted(address=account, currency="all"):
                    # taint entire balance of this token if not
                    if currency not in self.get_blacklist_value(account, "all"):
                        entire_balance = self.get_balance(account, currency, self._current_block)
                        # add token to "all"-list to mark it as done
                        self.add_currency_to_all(account, currency)
                        # do not add the token to the blacklist if the balance is 0, 0-values in the blacklist can lead to issues
                        if entire_balance > 0:
                            self.add_to_blacklist(address=account, amount=entire_balance, currency=currency, immediately=True)
                            self._logger.info(self._tx_log + f"Tainted entire balance ({format(entire_balance, '.2e')}) of token {currency} for account {account}.")

                # add the account to temp balances
                if account not in temp_balances:
                    temp_balances[account] = {}
                if currency not in temp_balances[account]:
                    temp_balances[account][currency] = self.get_balance(account, currency, self._current_block)

                # add the account to the temp blacklist if it is on the full blacklist
                if self.is_blacklisted(account, currency):
                    if account not in temp_blacklist:
                        temp_blacklist[account] = {}
                    if currency not in temp_blacklist[account]:
                        temp_blacklist[account][currency] = self.get_blacklist_value(account, currency)

            # update temp blacklist with the current transfer
            temp_blacklist = self.temp_transfer(temp_balances, temp_blacklist, transfer_sender, transfer_receiver, currency, amount)

            # update temp balances with the amount sent in the current transfer
            if transfer_sender != null_address:
                temp_balances[transfer_sender][currency] -= amount
            if transfer_receiver != null_address:
                temp_balances[transfer_receiver][currency] += amount

        # once the transfer has been processed, execute all resulting changes
        for account in temp_blacklist:
            for currency in temp_blacklist[account]:
                if self.is_blacklisted(account, currency):
                    difference = temp_blacklist[account][currency] - self.get_blacklist_value(account, currency)
                    if difference:
                        if difference > 0:
                            self.add_to_blacklist(account, amount=difference, currency=currency)
                        else:
                            self.remove_from_blacklist(account, amount=difference, currency=currency)
                elif temp_blacklist[account][currency] > 0:
                    self.add_to_blacklist(account, amount=temp_blacklist[account][currency], currency=currency)

    def check_gas_fees(self, transaction_log, transaction, block, sender):
        gas_price = transaction["gasPrice"]
        base_fee = block["baseFeePerGas"]
        gas_used = transaction_log["gasUsed"]
        miner = block["miner"]

        total_fee_paid = gas_price * gas_used
        paid_to_miner = (gas_price - base_fee) * gas_used
        proportion_paid_to_miner = paid_to_miner / total_fee_paid

        taint_proportion = self.get_blacklist_value(sender, "ETH") / self.get_balance(sender, "ETH", self._current_block)
        tainted_fee = int(total_fee_paid * taint_proportion)
        tainted_fee_to_miner = int(tainted_fee * proportion_paid_to_miner)

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
        if sender in temp_blacklist and currency in temp_blacklist[sender] and temp_blacklist[sender][currency] > 0:
            if temp_balances[sender][currency] == 0:
                if temp_blacklist[sender][currency] > 1000:
                    self._logger.warning(self._tx_log + f"The temp balance for account {sender} and currency {currency} is 0, but their blacklist value is {temp_blacklist[sender][currency]}.")
                temp_blacklist[sender][currency] = 0
                return temp_blacklist
            taint_proportion = temp_blacklist[sender][currency] / temp_balances[sender][currency]

            if taint_proportion > 1:
                difference = temp_blacklist[sender][currency] - temp_balances[sender][currency]
                self._logger.warning(self._tx_log + f"Account {sender} has more temp. taint than balance " +
                                     f"({temp_blacklist[sender][currency]} > {temp_balances[sender][currency]}). " +
                                     f"Tainting full transaction instead and reducing taint by {format(difference, '.2e')}.")
                temp_blacklist[sender][currency] -= difference
                taint_proportion = 1

            transferred_amount = int(amount * taint_proportion)

            # correct for rounding errors that would increase the total amount of taint
            # by limiting the transferred taint to the sent amount
            if transferred_amount > amount:
                self._logger.debug(f"Corrected rounding error that increased the taint by {format(transferred_amount - amount, '.2e')}.")
                transferred_amount = amount

            temp_blacklist[sender][currency] -= transferred_amount

            # do not transfer taint if receiver is null, since the tokens were burned
            if receiver == null_address:
                self._logger.info(self._tx_log + f"{format(transferred_amount, '.2e')} of tainted tokens {currency} ({format(amount, '.2e')} total) were burned.")
                return temp_blacklist

            if receiver not in temp_blacklist:
                temp_blacklist[receiver] = {currency: transferred_amount}
            elif currency not in temp_blacklist[receiver]:
                temp_blacklist[receiver][currency] = transferred_amount
            else:
                temp_blacklist[receiver][currency] += transferred_amount

        return temp_blacklist

    def transfer_taint(self, from_address: str, to_address: str, amount_sent: int, currency: str):
        # check if ETH or WETH, then calculate the amount that should be tainted
        balance = self.get_balance(from_address, currency, self._current_block)
        if balance == 0:
            self._logger.error(self._tx_log + "Balance is 0")
            exit(-1)
        taint_proportion = self.get_blacklist_value(from_address, currency) / balance

        if taint_proportion > 1:
            difference = self.get_blacklist_value(from_address, currency) - self.get_blacklist_value(from_address, currency)
            self._logger.warning(self._tx_log + f"Account {from_address} has more taint than balance " +
                                 f"({self.get_blacklist_value(from_address, currency)} > {balance}). " +
                                 f"Tainting full transaction instead and reducing taint by {difference}.")
            self.remove_from_blacklist(from_address, difference, currency, immediately=True)
            taint_proportion = 1

        transferred_amount = amount_sent * taint_proportion
        self.remove_from_blacklist(address=from_address, amount=transferred_amount, currency=currency)

        # do not transfer taint if receiver is 0, since the tokens were burned
        if to_address == null_address:
            self._logger.info(self._tx_log + f"{format(transferred_amount, '.2e')} of tainted tokens {currency} ({format(amount_sent, '.2e')} total) were burned.")
            return

        self.add_to_blacklist(address=to_address, amount=transferred_amount, currency=currency)

        self._logger.debug(self._tx_log + f"Transferred {format(transferred_amount, '.2e')} taint of {currency} from {from_address} to {to_address}")
        self._logger.debug(self._tx_log + f"Taint proportion was {format(taint_proportion * 100, '.5f')}% of the sent amount {format(amount_sent, '.2e')}, with a balance of {format(balance, '.2e')}")

    def add_account_to_blacklist(self, address: str, block: int, immediately=False):
        super().add_account_to_blacklist(address, block, True)
