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
checkpoint_location = parameters["CheckpointLocation"]

# read Etherscan API key from config
ETHERSCAN_API_KEY = parameters["EtherScanKey"]


def policy_test(policy, start_block, block_number, load_checkpoint, metrics_file=None, start_accounts: list = None, checkpoint_filename="blacklist_checkpoint.json"):
    blacklist_policy = policy(w3, checkpoint_file=checkpoint_location + checkpoint_filename, log_file=log_file, metrics_file=metrics_file)
    for account in start_accounts:
        blacklist_policy.add_account_to_blacklist(address=account, block=start_block)
    print(f"Blacklist at start: {blacklist_policy.get_blacklist()}")
    print("Amounts:")
    blacklist_policy.print_blacklisted_amount()

    blacklist_policy.propagate_blacklist(start_block, block_number, load_checkpoint=load_checkpoint)

    blacklist_policy.export_blacklist("data/finished_blacklist.json")

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
    # bZx theft
    start_block = 13557100
    start_accounts = ["0x74487eEd1E67F4787E8C0570E8D5d168a05254D4"]

    # vulcan forged hack
    start_block_2 = 13793875
    start_accounts_2 = ["0x48ad05a3B73c9E7fAC5918857687d6A11d2c73B1", "0xe3cD90be37A79D9da86b5E14E2F6042Cd0e53b66"]

    # ********* TESTING *************

    policy_test(FIFOPolicy, start_block_2, 10000, load_checkpoint=True, metrics_file="data/analytics/fifo.txt", start_accounts=start_accounts_2, checkpoint_filename="checkpoint_fifo.json")
    policy_test(SeniorityPolicy, start_block_2, 10000, load_checkpoint=True, metrics_file="data/analytics/seniority.txt", start_accounts=start_accounts_2,
                checkpoint_filename="checkpoint_seniority.json")
    policy_test(HaircutPolicy, start_block_2, 100000, load_checkpoint=True, metrics_file="data/analytics/haircut.txt", start_accounts=start_accounts_2, checkpoint_filename="checkpoint_haircut.json")
    policy_test(ReversedSeniorityPolicy, start_block_2, 10000, load_checkpoint=True, metrics_file="data/analytics/reversed_seniority.txt", start_accounts=start_accounts_2,
                checkpoint_filename="checkpoint_reversed_seniority.json")
    policy_test(PoisonPolicy, start_block_2, 10000, load_checkpoint=True, metrics_file="data/analytics/seniority.txt", start_accounts=start_accounts_2, checkpoint_filename="checkpoint_poison.json")
