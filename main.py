import configparser
import logging
import sys

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

# read Infura API link from config
remote_provider = Web3.HTTPProvider(parameters["InfuraLink"])

# use default Erigon URL for local provider
local_provider = Web3.HTTPProvider("http://localhost:8545")

log_file = parameters["LogFile"]
checkpoint_file = parameters["CheckpointFile"]

# read Etherscan API key from config
ETHERSCAN_API_KEY = parameters["EtherScanKey"]


def policy_test(policy, start_block, block_number, load_checkpoint, metrics_file=None):
    blacklist_policy = policy(w3, checkpoint_file=checkpoint_file, log_file=log_file, metrics_file=metrics_file)
    blacklist_policy.add_account_to_blacklist(address="0x11b815efB8f581194ae79006d24E0d814B7697F6", block=start_block)
    blacklist_policy.add_account_to_blacklist(address="0x529fFceC1Ee0DBBB822b29982B7D5ea7B8DcE4E2", block=start_block)
    print(f"Blacklist at start: {blacklist_policy.get_blacklist()}")
    print("Amounts:")
    blacklist_policy.print_blacklisted_amount()

    blacklist_policy.propagate_blacklist(start_block, block_number, load_checkpoint=load_checkpoint)

    blacklist_policy.export_blacklist("data/seniority_blacklist.json")

    print("***** Sanity Check *****")
    blacklist_policy.sanity_check()
    print("Sanity check complete.")

    print(blacklist_policy.get_blacklist_metrics())
    print("Amounts:")
    blacklist_policy.print_blacklisted_amount()


if __name__ == '__main__':
    print("")
    logger.info("************ Starting **************")

    # setup web3
    w3_local = Web3(local_provider)
    w3_remote = Web3(remote_provider)

    # PICK WEB3 PROVIDER
    w3 = w3_local

    # get the latest block and log it
    latest_block = w3.eth.get_block_number()
    logger.info(f"Latest block: {latest_block}.")

    # example block and transaction
    test_block = 14394958

    # ********* TESTING *************

    policy_test(FIFOPolicy, test_block, 100, load_checkpoint=True, metrics_file="data/fifo.txt")
    # policy_test(SeniorityPolicy, test_block, 100, load_checkpoint=False, metrics_file="data/fifo.txt")
    # policy_test(HaircutPolicy, test_block, 1000, load_checkpoint=True, metrics_file="data/haircut.txt")
    # policy_test(ReversedSeniorityPolicy, test_block, 1000, load_checkpoint=True, metrics_file="data/reversed_seniority.txt")
    # policy_test(PoisonPolicy, test_block, 500, load_checkpoint=True, metrics_file="data/seniority.txt")
    # haircut_policy_test(1000, load_checkpoint=True)
