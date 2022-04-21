import configparser
import logging
import sys

import requests.exceptions
from web3 import Web3

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

log_folder = parameters["LogFolder"]
checkpoint_location = parameters["CheckpointLocation"]
analytics_folder = parameters["AnalyticsFolder"]

# read Etherscan API key from config
ETHERSCAN_API_KEY = parameters["EtherScanKey"]


def policy_test(policy, start_block, block_number, load_checkpoint, metrics_folder=None, start_accounts: list = None):
    blacklist_policy = policy(w3, checkpoint_folder=checkpoint_location, log_folder=log_folder, metrics_folder=metrics_folder)
    for account in start_accounts:
        blacklist_policy.add_account_to_blacklist(address=account, block=start_block)

    try:
        blacklist_policy.propagate_blacklist(start_block, block_number, load_checkpoint=load_checkpoint)
    except KeyboardInterrupt:
        print("Keyboard interrupt received. Closing program.")
        print(f"Tainted transactions: ")
        blacklist_policy.print_tainted_transactions_per_account()
        return

    blacklist_policy.export_blacklist("data/finished_blacklist.json")

    print(blacklist_policy.get_blacklist_metrics())


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

    # example block and transaction
    # bZx theft
    start_block = 13557100
    start_accounts = ["0x74487eEd1E67F4787E8C0570E8D5d168a05254D4"]

    # vulcan forged hack
    start_block_2 = 13793875
    start_accounts_2 = ["0x48ad05a3B73c9E7fAC5918857687d6A11d2c73B1", "0xe3cD90be37A79D9da86b5E14E2F6042Cd0e53b66"]

    # ********* TESTING *************

    block_amount = 200000

    if len(sys.argv) != 2:
        print(f"Invalid argument string {sys.argv}.")
        exit(-2)

    policy_id = int(sys.argv[1])

    if policy_id == 0:
        policy_test(FIFOPolicy, start_block_2, block_amount, load_checkpoint=False, metrics_folder=analytics_folder, start_accounts=start_accounts_2)
    elif policy_id == 1:
        policy_test(SeniorityPolicy, start_block_2, block_amount, load_checkpoint=False, metrics_folder=analytics_folder, start_accounts=start_accounts_2)
    elif policy_id == 2:
        policy_test(HaircutPolicy, start_block_2, block_amount, load_checkpoint=False, metrics_folder=analytics_folder, start_accounts=start_accounts_2)
    elif policy_id == 3:
        policy_test(ReversedSeniorityPolicy, start_block_2, block_amount, load_checkpoint=False, metrics_folder=analytics_folder, start_accounts=start_accounts_2)
    elif policy_id == 4:
        policy_test(PoisonPolicy, start_block_2, block_amount, load_checkpoint=False, metrics_folder=analytics_folder, start_accounts=start_accounts_2)
    else:
        print(f"Invalid policy id {policy_id}. Must be a number between 0 and 4.")
