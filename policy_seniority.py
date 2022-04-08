import logging

from web3 import Web3

from blacklist import BufferedDictBlacklist
from blacklist_policy import BlacklistPolicy

delayed_write = False


class SeniorityPolicy(BlacklistPolicy):
    def __init__(self, w3: Web3, checkpoint_file, logging_level=logging.INFO, log_to_file=False, log_to_db=False):
        super().__init__(w3, checkpoint_file, BufferedDictBlacklist(), logging_level, log_to_file, log_to_db)

    def check_transaction(self, transaction_log, transaction, full_block, internal_transactions):
        sender = transaction["from"]
        receiver = transaction["to"]

        # write changes queued up in the last block
        if transaction["blockNumber"] > self._current_block >= 0:
            self._logger.debug(f"Writing changes, since transaction block {transaction['blockNumber']} > current block {self._current_block}...")
            self._blacklist.write_blacklist()
        self._current_block = transaction["blockNumber"]

        self._tx_log = f"Transaction https://etherscan.io/tx/{transaction['hash'].hex()} | "
        self._current_tx = transaction['hash'].hex()

        # if the sender has any blacklisted ETH, taint the paid gas fees
        if self.is_blacklisted(sender, "ETH"):
            self.check_gas_fees(transaction_log, transaction, full_block, sender)

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

        temp_blacklist = {}

    def check_gas_fees(self, transaction_log, transaction, full_block, sender):
        pass
