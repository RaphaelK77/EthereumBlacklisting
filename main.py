import configparser
import logging
import sys
from dataclasses import dataclass

import requests.exceptions
from web3 import Web3

from blacklist_policy import BlacklistPolicy
from policy_fifo import FIFOPolicy
from policy_haircut import HaircutPolicy
from policy_poison import PoisonPolicy
from policy_reversed_seniority import ReversedSeniorityPolicy
from policy_seniority import SeniorityPolicy

# configure logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

# read config.ini
config = configparser.ConfigParser()
config.read("config.ini")
parameters = config["PARAMETERS"]

# use default Erigon URL for local provider
local_provider = Web3.HTTPProvider("http://localhost:8545")

data_folder_root = parameters["DataFolder"]


@dataclass
class Dataset:
    name: str
    start_block: int
    block_number: int
    start_accounts: list
    data_folder: str


def policy_test(policy, dataset: Dataset, load_checkpoint, permanently_taint=False):
    blacklist_policy: BlacklistPolicy = policy(w3, data_folder=dataset.data_folder)

    print(f"Starting Policy test with policy '{blacklist_policy.get_policy_name()}' and dataset '{dataset.name}'.")

    for account in dataset.start_accounts:
        if permanently_taint:
            blacklist_policy.permanently_taint_account(account)
        else:
            blacklist_policy.add_account_to_blacklist(address=account, block=dataset.start_block)

    try:
        blacklist_policy.propagate_blacklist(dataset.start_block, dataset.block_number, load_checkpoint=load_checkpoint)
        print("Metrics:")
        print(blacklist_policy.get_blacklist_metrics())

    except KeyboardInterrupt:
        print("Keyboard interrupt received. Closing program.")
    finally:
        print(f"Tainted transactions: ")
        blacklist_policy.print_tainted_transactions_per_account()
        blacklist_policy.export_tainted_transactions(10)


if __name__ == '__main__':
    print("")
    logger.info("************ Starting **************")

    # setup web3
    w3 = Web3(local_provider)

    # get the latest block and log it
    try:
        latest_block = w3.eth.get_block_number()
        logger.info(f"Latest block: {latest_block}.")
    except requests.exceptions.ConnectionError:
        print("No node found at the given address.")
        exit(-1)

    # amount of blocks the blacklist policy should be propagated for
    block_amount = 200000

    # vulcan forged hack
    dataset_1 = Dataset("Vulcan Forged Hack", 13793875, block_amount, ["0x48ad05a3B73c9E7fAC5918857687d6A11d2c73B1", "0xe3cD90be37A79D9da86b5E14E2F6042Cd0e53b66"], data_folder_root + "dataset_1/")

    # afk system rug pull (tornado cash)
    dataset_2 = Dataset("AFKSystem rugpull", 13200582, block_amount, ["0x56Eb4A5F64Fa21E13548b95109F42fa08A644628"], data_folder_root + "dataset_2/")

    # AnubisDAO liquidity rug
    dataset_3 = Dataset("AnubisDAO liquidity rug", 13510000, block_amount, ["0x872254d530Ae8983628cb1eAafC51F78D78c86D9", "0x9fc53c75046900d1F58209F50F534852aE9f912a"],
                        data_folder_root + "dataset_3/")

    # Permanently taint tornado cash
    dataset_tornado = Dataset("Tornado.Cash", 1300000, block_amount, ["0xd90e2f925DA726b50C4Ed8D0Fb90Ad053324F31b"], data_folder_root + "tornado/")

    # ********* TESTING *************

    if len(sys.argv) != 2:
        print(f"Invalid argument string {sys.argv}.")
        exit(-2)

    policy_id = int(sys.argv[1])

    used_dataset = dataset_1

    load_checkpoint_all = True

    if policy_id == 0:
        policy_test(FIFOPolicy, used_dataset, load_checkpoint=load_checkpoint_all)
    elif policy_id == 1:
        policy_test(SeniorityPolicy, used_dataset, load_checkpoint=load_checkpoint_all)
    elif policy_id == 2:
        policy_test(HaircutPolicy, used_dataset, load_checkpoint=load_checkpoint_all)
    elif policy_id == 3:
        policy_test(ReversedSeniorityPolicy, used_dataset, load_checkpoint=load_checkpoint_all)
    elif policy_id == 4:
        policy_test(PoisonPolicy, used_dataset, load_checkpoint=load_checkpoint_all)
    else:
        print(f"Invalid policy id {policy_id}. Must be a number between 0 and 4.")
