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

# read Etherscan API key from config
ETHERSCAN_API_KEY = parameters["EtherScanKey"]


@dataclass
class Dataset:
    name: str
    start_block: int
    block_number: int
    start_accounts: list
    data_folder: str


def policy_test(policy, dataset: Dataset, load_checkpoint):
    blacklist_policy: BlacklistPolicy = policy(w3, data_folder=dataset.data_folder)

    print(f"Starting Policy test with policy '{blacklist_policy.get_policy_name()}' and dataset '{dataset.name}'.")

    for account in dataset.start_accounts:
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

    # ********* TESTING *************

    if len(sys.argv) != 2:
        print(f"Invalid argument string {sys.argv}.")
        exit(-2)

    policy_id = int(sys.argv[1])

    dataset = dataset_1

    if policy_id == 0:
        policy_test(FIFOPolicy, dataset, load_checkpoint=True)
    elif policy_id == 1:
        policy_test(SeniorityPolicy, dataset, load_checkpoint=True)
    elif policy_id == 2:
        policy_test(HaircutPolicy, dataset, load_checkpoint=True)
    elif policy_id == 3:
        policy_test(ReversedSeniorityPolicy, dataset, load_checkpoint=True)
    elif policy_id == 4:
        policy_test(PoisonPolicy, dataset, load_checkpoint=True)
    else:
        print(f"Invalid policy id {policy_id}. Must be a number between 0 and 4.")
