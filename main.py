import configparser
import logging
import sys

from web3 import Web3

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


def policy_test(policy, start_block, block_number, load_checkpoint):
    blacklist_policy = policy(w3, checkpoint_file=checkpoint_file, log_file=log_file)
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
    test_tx = "0x7435b60090e0347fc09bb961e02a4dd5baa59ce0ed83de2f0dffca36243d66f9"

    transfer_test_tx = "0xea2ea4fd6a58cecb2de513bdc8448b8079da9df3dfafd7b01a219b30afdc6ecd"
    internal_test_tx = "0xd0c2ffc366765cc6414cc07f4b4c2befb263af2dbd62f2ba95bc45ea200b79c6"

    # ********* TESTING *************

    # policy_test(SeniorityPolicy, test_block, 100, load_checkpoint=False)
    # policy_test(HaircutPolicy, test_block, 100, load_checkpoint=False)
    # policy_test(ReversedSeniorityPolicy, test_block, 1000, load_checkpoint=True)
    # policy_test(PoisonPolicy, test_block, 500, load_checkpoint=True)
    # haircut_policy_test(1000, load_checkpoint=True)
