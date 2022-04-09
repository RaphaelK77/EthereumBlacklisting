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
        if to_address == self._eth_utils.null_address or to_address is None:
            self._logger.info(self._tx_log + f"{amount_sent} tokens were burned, of which {transferred_amount} were blacklisted.")
            return

        self.add_to_blacklist(to_address, transferred_amount, currency)

        self._logger.debug(self._tx_log + f"Transferred {format(transferred_amount, '.2e')} taint of {currency} from {from_address} to {to_address}")
        self.save_log("DEBUG", "TRANSFER", from_address, to_address, transferred_amount, currency)

    def add_to_blacklist(self, address: str, amount: int, currency: str, immediately=False):
        super().add_to_blacklist(address, amount=amount, currency=currency, immediately=not self._buffered)

    def remove_from_blacklist(self, address: str, amount: Union[int, float], currency: str, immediately=False):
        super().remove_from_blacklist(address, amount, currency, immediately=not self._buffered)

    def check_transaction(self, transaction_log, transaction, full_block, internal_transactions):
        sender = transaction["from"]
        receiver = transaction["to"]

        # write changes queued up in the last block if buffering is enabled
        if transaction["blockNumber"] > self._current_block >= 0 and self._buffered:
            self._logger.debug(f"Writing changes, since transaction block {transaction['blockNumber']} > current block {self._current_block}...")
            self._blacklist.write_blacklist()

        # update progress
        self._current_block = transaction["blockNumber"]
        self._tx_log = f"Transaction https://etherscan.io/tx/{transaction['hash'].hex()} | "
        self._current_tx = transaction['hash'].hex()

        # skip the remaining code if there were no smart contract events
        if not transaction_log["logs"]:

            # if any of the sender's ETH is blacklisted, taint any sent ETH
            # (this will be done as part of the transfers if the tx is a smart contract invocation)
            if self.is_blacklisted(sender, "ETH"):
                if transaction["value"] > 0:
                    # transfer taint from sender to receiver (no need to check for "all", since ETH is tainted immediately)
                    self.transfer_taint(from_address=sender, to_address=receiver, amount_sent=transaction["value"], currency="ETH")

            # if the sender (still) has any blacklisted ETH, taint the paid gas fees
            if self.is_blacklisted(sender, "ETH"):
                self.check_gas_fees(transaction_log, transaction, full_block, sender)
            return

        # get all transfers
        transfer_events = self._eth_utils.get_all_events_of_type_in_tx(transaction_log, ["Transfer"])

        # get all internal transactions
        if internal_transactions and transaction["value"]:
            if len(internal_transactions) > 1:
                transfer_events = [internal_transactions[0]] + transfer_events + internal_transactions[1:]
            else:
                transfer_events = [internal_transactions[0]] + transfer_events
        else:
            transfer_events += internal_transactions

        temp_blacklist = {}

        for transfer_event in transfer_events:
            currency = transfer_event["address"]
            transfer_sender = transfer_event['args']['from']
            transfer_receiver = transfer_event['args']['to']
            amount = transfer_event['args']['value']

            if self._eth_utils.is_eth(currency):
                currency = "ETH"

            for account in transfer_sender, transfer_receiver:
                # skip null address
                if account == self._eth_utils.null_address:
                    continue

                if currency != "ETH" and self.is_blacklisted(address=account, currency="all"):
                    self.fully_taint_token(account, currency)

                # fill temp blacklist if buffering is enabled
                if self._buffered and self.is_blacklisted(account, currency):
                    if account not in temp_blacklist:
                        temp_blacklist[account] = {}
                    if currency not in temp_blacklist[account]:
                        temp_blacklist[account][currency] = self.get_blacklist_value(account, currency)

            if self._buffered:  # TODO: check if in temp blacklist
                temp_blacklist = self.temp_transfer(temp_blacklist, transfer_sender, transfer_receiver, currency, amount)
            elif self.is_blacklisted(transfer_sender, currency):
                self.transfer_taint(transfer_sender, transfer_receiver, amount, currency)

        if self.is_blacklisted(sender, "ETH"):
            self.check_gas_fees(transaction_log, transaction, full_block, sender)

    def check_gas_fees(self, transaction_log, transaction, full_block, sender):
        gas_price = transaction["gasPrice"]
        base_fee = full_block["baseFeePerGas"]
        gas_used = transaction_log["gasUsed"]
        miner = full_block["miner"]

        total_fee_paid = gas_price * gas_used
        paid_to_miner = (gas_price - base_fee) * gas_used

        if self._buffered:
            # TODO
            pass
        else:
            tainted_fee = min(total_fee_paid, self.get_blacklist_value(sender, "ETH"))
            self.remove_from_blacklist(sender, tainted_fee, "ETH")
            tainted_fee_to_miner = min(paid_to_miner, self.get_blacklist_value(sender, "ETH"))
            self.add_to_blacklist(miner, tainted_fee_to_miner, "ETH")

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
