import logging
import time

import web3.exceptions
from web3 import Web3

import utils

START_ADDRESS = "0x39fA8c5f2793459D6622857E7D9FbB4BD91766d3"
last_account = START_ADDRESS
UPDATE_INTERVAL = 10000


# TEST_ADDRESS = "0xA1E4380A3B1f749673E270229993eE55F35663b4"

class Verifier:
    def __init__(self, w3: Web3):
        self.w3 = w3

    def block_exists(self, block: int):
        try:
            self.w3.eth.get_block(block)
            logging.debug(f"Block {block} exists.")
            return True
        except web3.exceptions.BlockNotFound:
            logging.debug(f"Block {block} does not exist.")
            return False

    def block_state_exists(self, block: int):
        global last_account

        transactions = self.w3.eth.get_block(block, full_transactions=True)["transactions"]
        if transactions:
            last_account = transactions[0]["from"]
            logging.debug(f"Changed last account to '{last_account}'.")
        try:
            self.w3.eth.get_balance(last_account, block)
            return True
        except ValueError:
            return False
        except web3.exceptions.BlockNotFound:
            return False

    def block_exists_both(self, block: int) -> (bool, bool):
        """
        availability and validity check in a single request
        :param block: block number
        :return: bool available, bool valid
        """
        try:
            self.w3.eth.get_balance(START_ADDRESS, block)
            return True, True
        except ValueError:
            return True, False
        except web3.exceptions.BlockNotFound:
            return False, False

    def block_range_exists(self, start_block, end_block):
        return [self.block_exists(block) for block in range(start_block, end_block)]

    def block_range_exists_state(self, start_block, end_block):
        return [self.block_state_exists(block) for block in range(start_block, end_block)]

    def block_range_exists_all(self, start_block, end_block):
        for block in range(start_block, end_block):
            if not self.block_exists(block):
                return False
        return True

    def block_range_exists_any(self, start_block, end_block):
        for block in range(start_block, end_block):
            if self.block_exists(block):
                return True
        return False

    def block_range_exists_any_state(self, start_block, end_block):
        for block in range(start_block, end_block):
            if self.block_state_exists(block):
                return True
        return False

    def count_blocks_in_range(self, start_block, end_block):
        return sum([self.block_exists(block) for block in range(start_block, end_block)])

    def count_blocks_in_range_state(self, start_block, end_block):
        return sum([self.block_state_exists(block) for block in range(start_block, end_block)])

    def full_availability_report(self, start_block, end_block):
        available_list = []
        last_available = -2
        valid_list = []
        last_valid = -2
        total_valid = 0
        total_available = 0

        total_blocks = end_block - start_block + 1
        start_time = time.time()

        logging.info(f"Starting availability report from blocks {start_block:,} to {end_block:,}.")

        for block in range(start_block, end_block):
            # available blocks
            # if block is available
            exists, valid = self.block_exists_both(block)
            if exists:
                total_available += 1
                if last_available < block - 1:
                    available_list.append(block)
                last_available = block

                # valid blocks
                if valid:
                    total_valid += 1
                    if last_valid < block - 1:
                        valid_list.append(block)
                    last_valid = block
                elif last_valid == block - 1:
                    logging.debug(f"Block {block} is invalid, last valid was {last_valid}. Appending last valid to list.")
                    valid_list.append(last_valid)

            # if block is first unavailable
            elif last_available == block - 1:
                available_list.append(last_available)

                # if block is unavailable and last block was valid
                if last_valid == block - 1:
                    logging.debug(f"Block {block} is unavailable, last valid was {last_valid}. Appending last valid to list.")
                    valid_list.append(last_valid)

            logging.debug(f"Checked block {block}.")
            processed_blocks = block - start_block + 1
            if processed_blocks % UPDATE_INTERVAL == 0 and processed_blocks > 0:
                elapsed_time = time.time() - start_time
                logging.info(f"Availability report {format(processed_blocks / total_blocks * 100, '.2f')}% complete. Elapsed time: {utils.format_seconds_as_time(elapsed_time)}. " +
                             f"Remaining: {utils.format_seconds_as_time((elapsed_time * (total_blocks - processed_blocks)) / processed_blocks)}. " +
                             f"Checked/Available/Valid so far: {processed_blocks:,}/{total_available:,}/{total_valid:,}. " +
                             f"{format(processed_blocks / elapsed_time,'.0f')} blocks/s. Current block: {block:,}")

        if last_valid == end_block - 1:
            valid_list.append(last_valid)
        if last_available == end_block - 1:
            available_list.append(last_available)

        total_time = time.time() - start_time
        logging.info(f"Report complete. Total time: {utils.format_seconds_as_time(total_time)}, average performance: {format(total_blocks/total_time, '.0f')} blocks/s")

        print("Available block ranges: ")
        print_ranges(available_list)
        print(f"Total available: {total_available:,}/{total_blocks:,}")
        print("")
        print("Valid block ranges: ")
        print_ranges(valid_list)
        print(f"Total valid: {total_valid:,}")

    def valid_ranges_state(self, start_block, end_block):
        valid_list = []
        invalid_list = []
        last_valid = start_block
        last_invalid = start_block
        for block in range(start_block, end_block):
            if self.block_state_exists(block):
                if last_valid <= last_invalid:
                    valid_list.append(last_valid)
                    invalid_list.append(last_invalid)
                last_valid = block
            else:
                if last_invalid <= last_valid:
                    valid_list.append(last_valid)
                    invalid_list.append(last_invalid)
                last_invalid = block
        if last_valid > last_invalid:
            valid_list += last_valid

        return valid_list, invalid_list


def print_ranges(range_list: list):
    for i in range(0, len(range_list), 2):
        start = range_list[i]
        end = range_list[i + 1]
        if start == end:
            print(f"{start:,}")
        else:
            print(f"{start:,}-{end:,}")


if __name__ == "__main__":
    w3 = Web3(Web3.HTTPProvider())
    verifier = Verifier(w3)

    # print(verifier.count_blocks_in_range(100000, 200000))
    # print(verifier.count_blocks_in_range_state(100000, 200000))
    # print(verifier.valid_ranges_state(100000, 200000))
    # print(verifier.block_range_exists(10000, 20000))
    verifier.full_availability_report(0, 1000000)
    # verifier.block_range_exists_any_state(500000, 1000000)
