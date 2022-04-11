import configparser
import json
import logging
import sys
from json import JSONDecodeError
from typing import Union

import requests
import web3.constants
from hexbytes import HexBytes
from web3 import Web3
from web3 import constants
from web3.datastructures import AttributeDict
from web3.exceptions import BadFunctionCallOutput, ContractLogicError

import database as db
import policy_haircut
from abis import function_abis
from ethereum_utils import EthereumUtils
from policy_poison import PoisonPolicy
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

# read Etherscan API key from config
ETHERSCAN_API_KEY = parameters["EtherScanKey"]


def get_balance(account: str, block: int):
    if block < 0:
        logger.error(f"Block number cannot be negative (was {block}).")
        return None
    logger.info(f"Getting balance for account {account} at block {block}.")
    try:
        wei = w3_local.eth.get_balance(account, block)
    except ValueError:
        logger.warning(f"World state at block {block} has not been archived and balance cannot be retrieved.")
        return None
    return wei / constants.WEI_PER_ETHER


def poison_test():
    poison = PoisonPolicy(w3_local)
    poison.add_to_blacklist("0x8C6AE7a05a1dE57582ae2768204276c0ff47ed03")

    print(f"Blacklisted amount start: {poison.get_blacklisted_amount(60000) / web3.constants.WEI_PER_ETHER} ETH")

    poison.propagate_blacklist(50000, 1000)

    print(f"Blacklist length: {len(poison.blacklist)}")
    print(f"Blacklisted amount: {poison.get_blacklisted_amount(60000) / web3.constants.WEI_PER_ETHER} ETH")


def is_contract(address: str):
    """
    Check if the given address is a smart contract

    :param address: Ethereum address
    :return: True if smart contract
    """
    return w3.eth.get_code(address).hex() != "0x"


def get_abi(address: str, block: int):
    abi_from_database = database.get_abi(address, block)
    if abi_from_database:
        logger.debug(f"Retrieving ABI for address '{address}' from database.")
        try:
            json.loads(abi_from_database)
        except (TypeError, JSONDecodeError):
            logger.error(f"Decoding ABI from database failed. ABI was: {abi_from_database}")
            exit(-1)
        return abi_from_database
    elif abi_from_database is None:
        return None
    logger.debug(f"Requesting ABI for address '{address}' from EtherScan.")
    api_call = f"https://api.etherscan.io/api?module=contract&apikey={ETHERSCAN_API_KEY}&action=getabi&address={address}"
    response = requests.get(api_call)
    response_json = response.json()
    if "result" in response_json and response_json["result"] != "Contract source code not verified":
        abi = response_json["result"]
    else:
        abi = None
    database.add_contract(address, abi, block)
    return abi


def list_functions_for_contract(address: str, block: int):
    abi = get_abi(address, block)
    if not abi:
        return []
    try:
        function_list = [entry["name"] for entry in json.loads(abi) if entry["type"] == "function"]
    except JSONDecodeError:
        logger.error(f"JSON decoding of ABI failed for address '{address}'. ABI was '{abi}'.")
        return []
    return function_list


def get_contract(address: str, block: int):
    """
    Retrieve the ABI of the given contract address from Etherscan and return a Web3 contract

    :param address: Ethereum address of the contract
    :param block: block at which the last access should be recorded
    :return: web3 Contract object
    """
    abi = get_abi(address, block)
    if not abi:
        return None
    return w3.eth.contract(address=Web3.toChecksumAddress(address), abi=abi)


def get_invoked_function(transaction_dict: dict = None, transaction_hash: HexBytes = None):
    if transaction_hash:
        transaction_dict = w3.eth.get_transaction(transaction_hash)

    contract_addr = transaction_dict["to"]
    block = transaction_dict["blockNumber"]
    contract = get_contract(contract_addr, block)
    if not contract:
        return None
    try:
        function_input = contract.decode_function_input(transaction_dict["input"])
    except ValueError:
        return None
    function_signature = function_input[0]
    return function_signature


def shutdown():
    """
    Perform cleanup and exit the program

    :return:
    """
    database.cleanup()
    exit(0)


def get_input_data(transaction: Union[AttributeDict, dict], block: int):
    contract_address = transaction["to"]
    contract = get_contract(contract_address, block)
    if not contract:
        return None
    try:
        function_input = contract.decode_function_input(transaction["input"])
    except ValueError:
        return None
    return function_input


def get_swap_path(transaction, block: int):
    input_data = get_input_data(transaction, block)
    if not input_data:
        return None
    currency_list = []
    function_input = input_data[1]
    if "path" not in function_input:
        logger.debug(f"No path found in function input {function_input} for transaction {transaction}.")
        return "[could not be determined]"
    for currency_address in function_input["path"]:
        request = eth_utils.get_contract_name_symbol(currency_address)
        if not request:
            return None
        name, symbol = request
        if symbol:
            currency_list.append(symbol)
        else:
            currency_list.append(name)
    return " -> ".join(currency_list)


def get_swap_tokens(contract_address: str):
    """
    Gets the addresses of the token pair of a DEX smart contract

    :param contract_address: address of the smart contract
    :return: token0, token1 / None, None if an error occurs
    """
    token_functions_abi = function_abis["Tokens"]

    contract = w3.eth.contract(address=Web3.toChecksumAddress(contract_address), abi=token_functions_abi)

    token0 = None
    token1 = None
    try:
        token0 = contract.functions.token0().call({})
        token1 = contract.functions.token1().call({})
    except BadFunctionCallOutput:
        logger.warning(f"token0 or token1 function for DEX contract at {contract_address} could not be executed.")
    except ContractLogicError:
        logger.warning(f"Smart contract at {contract_address} does not support token0 or token1 functions.")

    return token0, token1


def haircut_policy_test(block_number, load_checkpoint):
    blacklist_policy = policy_haircut.HaircutPolicy(w3, checkpoint_file="data/blacklist_checkpoint.json", logging_level=logging.INFO, log_to_file=True, log_to_db=True)
    blacklist_policy.add_account_to_blacklist(address="0x11b815efB8f581194ae79006d24E0d814B7697F6", block=test_block)
    blacklist_policy.add_account_to_blacklist(address="0x529fFceC1Ee0DBBB822b29982B7D5ea7B8DcE4E2", block=test_block)
    print(f"Blacklist at start: {blacklist_policy.get_blacklist()}")
    print("Amounts:")
    blacklist_policy.print_blacklisted_amount()

    blacklist_policy.propagate_blacklist(test_block, block_number, load_checkpoint=load_checkpoint)

    print(f"Final blacklist: {blacklist_policy.get_blacklist()}")
    print(blacklist_policy.get_blacklist_metrics())
    print("Amounts:")
    blacklist_policy.print_blacklisted_amount()


def seniority_policy_test(start_block, block_number, load_checkpoint):
    blacklist_policy = SeniorityPolicy(w3, checkpoint_file="data/blacklist_checkpoint.json", logging_level=logging.INFO, log_to_file=True, log_to_db=False)
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

    # read database location from config and open it
    database = db.Database(parameters["Database"])

    # get the latest block and log it
    latest_block = w3.eth.get_block_number()
    logger.info(f"Latest block: {latest_block}.")

    # example block and transaction
    test_block = 14394958
    test_tx = "0x7435b60090e0347fc09bb961e02a4dd5baa59ce0ed83de2f0dffca36243d66f9"

    transfer_test_tx = "0xea2ea4fd6a58cecb2de513bdc8448b8079da9df3dfafd7b01a219b30afdc6ecd"
    internal_test_tx = "0xd0c2ffc366765cc6414cc07f4b4c2befb263af2dbd62f2ba95bc45ea200b79c6"

    # ********* TESTING *************

    seniority_policy_test(test_block, 20, load_checkpoint=False)
    # haircut_policy_test(1000, load_checkpoint=True)
    # eth_utils.get_internal_transactions("0xc1a808b5232867f15632fc226ebf229505cbffa153fb0e7309131faef938825c")
    # eth_utils.get_internal_transactions("0x5b55f2e94a62ff26d9a4f3fa27b22da533be447377b3a6f73bf1c3edf906edcd")

    shutdown()
