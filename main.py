import argparse
import configparser
import logging
import sys
from dataclasses import dataclass

import requests.exceptions
from web3 import Web3

from policies.blacklist_policy import BlacklistPolicy
from policies.policy_fifo import FIFOPolicy
from policies.policy_haircut import HaircutPolicy
from policies.policy_poison import PoisonPolicy
from policies.policy_reversed_seniority import ReversedSeniorityPolicy
from policies.policy_seniority import SeniorityPolicy

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
    """
    Represents a dataset, including the experiment range, starting accounts and output folder
    """
    name: str
    start_block: int
    block_number: int
    start_accounts: list
    data_folder: str
    permanent_taint: bool = False


def policy_test(policy, dataset: Dataset, load_checkpoint):
    """
    Runs the provided policy

    :param policy: the blacklisting policy to be used
    :param dataset: the dataset containing the parameters for execution
    :param load_checkpoint: set true to load an existing checkpoint, false to ignore checkpoints
    """
    blacklist_policy: BlacklistPolicy = policy(w3, data_folder=dataset.data_folder)

    print(f"Starting Policy test with policy '{blacklist_policy.get_policy_name()}' and dataset '{dataset.name}'.")

    for account in dataset.start_accounts:
        if dataset.permanent_taint:
            blacklist_policy.permanently_taint_account(account)
        else:
            blacklist_policy.add_account_to_blacklist(address=account, block=dataset.start_block)

    try:
        blacklist_policy.propagate_blacklist(dataset.start_block, dataset.block_number, load_checkpoint=load_checkpoint)
        print("Metrics:")
        print(blacklist_policy.get_blacklist_metrics())

        print(f"Tainted transactions: ")
        blacklist_policy.print_tainted_transactions_per_account()
        blacklist_policy.export_tainted_transactions(10)

    except ValueError as e:
        if e.args and "code" in e.args[0] and e.args[0]["code"] == -32000:
            logger.error(f"ValueError: the given start block {dataset.start_block:,} is likely pruned.")
            exit(-32)
        else:
            raise e

    except KeyboardInterrupt:
        print("Keyboard interrupt received. Closing program.")

        print(f"Tainted transactions: ")
        blacklist_policy.print_tainted_transactions_per_account()
        blacklist_policy.export_tainted_transactions(10)


if __name__ == '__main__':
    logger.info("************ Starting **************")

    # setup web3
    w3 = Web3(local_provider)

    # get the latest synchronized block and log it
    # quit the program if no node was found
    try:
        latest_block = w3.eth.get_block_number()
        logger.info(f"Latest block: {latest_block}.")
    except requests.exceptions.ConnectionError:
        logger.error("No node found at the given address.")
        exit(-1)

    # ********* DATASETS *************

    datasets = []

    # amount of blocks the blacklist policy should be propagated for
    block_amount = 200000

    # vulcan forged hack
    datasets.append(
        Dataset("Vulcan Forged Hack", 13793875, block_amount, ["0x48ad05a3B73c9E7fAC5918857687d6A11d2c73B1", "0xe3cD90be37A79D9da86b5E14E2F6042Cd0e53b66"], data_folder_root + "dataset_1/"))

    # afk system rug pull (tornado cash)
    datasets.append(Dataset("AFKSystem rugpull", 13200582, block_amount, ["0x56Eb4A5F64Fa21E13548b95109F42fa08A644628"], data_folder_root + "dataset_2/"))

    # AnubisDAO liquidity rug
    datasets.append(Dataset("AnubisDAO liquidity rug", 13510000, block_amount, ["0x872254d530Ae8983628cb1eAafC51F78D78c86D9", "0x9fc53c75046900d1F58209F50F534852aE9f912a"],
                            data_folder_root + "dataset_3/"))

    # Permanently taint tornado cash (different accounts for 0.1, 1, 10 and 100 ETH)
    datasets.append(Dataset("Tornado.Cash", 13000000, block_amount, ["0x910Cbd523D972eb0a6f4cAe4618aD62622b39DbF", "0x12D66f87A04A9E220743712cE6d9bB1B5616B8Fc",
                                                                     "0x47CE0C6eD5B0Ce3d3A51fdb1C52DC66a7c3c2936", "0xA160cdAB225685dA1d56aa342Ad8841c3b53f291"], data_folder_root + "tornado/", True))

    # ********* TESTING *************

    parser = argparse.ArgumentParser(description="Test a policy with a predefined dataset")
    parser.add_argument("--policy", type=str, required=True, help="Picked policy out of 'Poison', 'Haircut', 'FIFO', 'Seniority', or 'Reversed_Seniority'")
    parser.add_argument("--dataset", type=int, required=True, help=f"Number of the chosen dataset (1 - {len(datasets)})")

    args = parser.parse_args()

    load_checkpoint_all = True

    picked_policy = args.policy.lower()
    picked_dataset = args.dataset

    used_dataset = None

    if 1 <= picked_dataset <= len(datasets):
        used_dataset = datasets[picked_dataset - 1]
    else:
        logger.error(f"Dataset {picked_dataset} does not exist.")
        exit(-2)

    if picked_policy == "fifo":
        policy_test(FIFOPolicy, used_dataset, load_checkpoint=load_checkpoint_all)
    elif picked_policy == "seniority":
        policy_test(SeniorityPolicy, used_dataset, load_checkpoint=load_checkpoint_all)
    elif picked_policy == "haircut":
        policy_test(HaircutPolicy, used_dataset, load_checkpoint=load_checkpoint_all)
    elif picked_policy == "reversed_seniority":
        policy_test(ReversedSeniorityPolicy, used_dataset, load_checkpoint=load_checkpoint_all)
    elif picked_policy == "poison":
        policy_test(PoisonPolicy, used_dataset, load_checkpoint=load_checkpoint_all)
    else:
        logger.error(f"Invalid policy name {picked_policy}.")
        exit(-2)
