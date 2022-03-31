import json
import logging
import sys
from json import JSONDecodeError

import requests
import web3.constants
from typing import Union, List, Tuple, Optional

from hexbytes import HexBytes
from web3 import Web3
from web3 import constants
from web3.datastructures import AttributeDict
from web3.exceptions import BadFunctionCallOutput, ContractLogicError
from web3.logs import DISCARD

import database as db
import utils
from abis import event_abis, function_abis
from data_structures import Transaction
from policy_poison import PoisonPolicy

import configparser

from utils import format_log_dict

# configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)

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
        logging.error(f"Block number cannot be negative (was {block}).")
        return None
    logging.info(f"Getting balance for account {account} at block {block}.")
    try:
        wei = w3_local.eth.get_balance(account, block)
    except ValueError:
        logging.warning(f"World state at block {block} has not been archived and balance cannot be retrieved.")
        return None
    return wei / constants.WEI_PER_ETHER


def print_dict(dictionary):
    for _key in dictionary:
        print(f"'{_key}': {dictionary[_key]}")


def print_logs(receipt):
    for log in receipt["logs"]:
        print_dict(log)
        print("")


def transactions_for_block(block: int) -> list:
    """
    Fetches all transactions in a block and returns them as Transaction objects.
    :param block: block to scan
    :return: list of transactions
    """
    transaction_list = []
    for _transaction in w3.eth.get_block(block, full_transactions=True)["transactions"]:
        _transaction = dict(_transaction)
        db_result = get_contract_name_symbol(_transaction['to'])
        if db_result:
            name, symbol = db_result
            function_sig = get_invoked_function(_transaction)
            if function_sig:
                _transaction["function"] = function_sig.fn_name
            if symbol:
                _transaction["to_sc"] = f"{name} - {symbol} ({_transaction['to']})"
            elif name:
                _transaction["to_sc"] = f"{name} ({_transaction['to']})"
        _tx = Transaction(_transaction)
        if _tx.is_swap():
            _tx.swap_path = get_swap_path(_transaction, block)
        transaction_list.append(_tx)

    return transaction_list


def dict_to_transaction(attribute_dict: AttributeDict) -> Transaction:
    _transaction = dict(attribute_dict)

    # get name and symbol if the receiver is a smart contract
    db_result = get_contract_name_symbol(_transaction['to'])

    if db_result:
        name, symbol = db_result
        function_sig = get_invoked_function(_transaction)
        if function_sig:
            _transaction["function"] = function_sig.fn_name
        if symbol:
            _transaction["to"] = f"{name} - {symbol} ({_transaction['to']})"
        elif name:
            _transaction["to"] = f"{name} ({_transaction['to']})"

    return Transaction(_transaction)


def poison_test():
    poison = PoisonPolicy(w3_local)
    poison.add_to_blacklist("0x8C6AE7a05a1dE57582ae2768204276c0ff47ed03", -1, "ETH")

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
        logging.debug(f"Retrieving ABI for address '{address}' from database.")
        try:
            json.loads(abi_from_database)
        except (TypeError, JSONDecodeError):
            logging.error(f"Decoding ABI from database failed. ABI was: {abi_from_database}")
            exit(-1)
        return abi_from_database
    elif abi_from_database is None:
        return None
    logging.debug(f"Requesting ABI for address '{address}' from EtherScan.")
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
        logging.error(f"JSON decoding of ABI failed for address '{address}'. ABI was '{abi}'.")
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


def get_contract_name_symbol_old(address: str, block: int, force_refresh=False):
    """
    DEPRECATED Get the name and symbol of a smart contract address

    :param force_refresh: stops database check and overwrites already saved data
    :param address: ethereum account address
    :param block: block at which the request was made
    :return: (name, symbol) or None if address is not a contract
    """
    # return from database if already saved
    if not force_refresh:
        db_request = database.get_name_symbol(address, block)
        if db_request:
            return db_request

    if not is_contract(address):
        return None

    # get all functions
    function_list = list_functions_for_contract(address, block)

    # if not supported by contract, use etherscan api
    if "name" not in function_list:
        api_call = f"https://api.etherscan.io/api?module=contract&apikey={ETHERSCAN_API_KEY}&action=getsourcecode&address={address}"
        response = requests.get(api_call)
        response_json = response.json()
        if "result" in response_json:
            if "ContractName" in response_json["result"][0]:
                name = response_json["result"][0]["ContractName"]
                database.set_name_symbol(address, name, None)
                return name, None
            response_json["result"][0]["SourceCode"] = "..."
            response_json["result"][0]["ABI"] = "..."
            logging.warning(f"No name found for contract '{address}'. Response was: {response_json}")
        logging.warning(f"No result received on EtherScan API call. Response was: {response_json}")
        return None, None

    contract = get_contract(address, block)
    name = contract.functions.name().call()

    symbol = None
    if "symbol" in function_list:
        symbol = contract.functions.symbol().call()

    database.set_name_symbol(address, name, symbol)

    return name, symbol


def get_contract_name_symbol(address: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Retrieves the token name and symbol from a token address

    :param address: Ethereum address
    :return: (name, symbol) as string if available, else None for each unavailable field
    """
    name_symbol_abi = function_abis["Name+Symbol"]

    contract = w3.eth.contract(address=Web3.toChecksumAddress(address), abi=name_symbol_abi)

    name = None
    symbol = None

    try:
        name = contract.functions.name().call()
        symbol = contract.functions.symbol().call()
    except web3.exceptions.BadFunctionCallOutput:
        logging.debug(f"Name and/or Symbol for {address} could not be retrieved, since it is not a smart contract.")
    except web3.exceptions.ContractLogicError:
        logging.debug(f"Name and/or Symbol function of smart contract at {address} could does not exist.")

    return name, symbol


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
        logging.debug(f"No path found in function input {function_input} for transaction {transaction}.")
        return "[could not be determined]"
    for currency_address in function_input["path"]:
        request = get_contract_name_symbol(currency_address)
        if not request:
            return None
        name, symbol = request
        if symbol:
            currency_list.append(symbol)
        else:
            currency_list.append(name)
    return " -> ".join(currency_list)


def get_token_balance(account: str, token_address: str, block: int = None):
    """
    Retrieves the token balance of the given account at the given block

    :param account: Ethereum account
    :param token_address: Ethereum address of token
    :param block: block to be executed at
    :return: token balance, -1 if it cannot be retrieved
    """

    if block is None:
        block = w3.eth.get_block_number()

    token_contract_abi = [{"type": "function", "name": "balanceOf", "constant": "true", "payable": "false", "inputs": [{"name": "", "type": "address"}], "outputs": [{"name": "", "type": "uint256"}]}]

    contract = w3.eth.contract(address=Web3.toChecksumAddress(token_address), abi=token_contract_abi)

    try:
        balance = contract.functions.balanceOf(account).call({}, block)
    except web3.exceptions.BadFunctionCallOutput:
        logging.warning(f"BalanceOf function for token smart contract at {token_address} could not be executed.")
        balance = -1

    return balance


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
        logging.warning(f"token0 or token1 function for DEX contract at {contract_address} could not be executed.")
    except ContractLogicError:
        logging.warning(f"Smart contract at {contract_address} does not support token0 or token1 functions.")

    return token0, token1


def get_all_events_of_type_in_tx(receipt: AttributeDict, event_types: List[str]):
    """
    Retrieves all events of the given types from the logs of the given transaction

    :param receipt: transaction receipt
    :param event_types: the type of the events (Transfer, Swap, Deposit, Withdrawal)
    :return: dictionary of {log_id: decoded_log}
    """
    _log_dict = {}

    for event_type in event_types:
        checked_addresses = []

        if event_type not in event_abis:
            logging.error(f"Could not get events of type {event_type} from transaction; type unkown.")
            continue

        token_contract_abi = event_abis[event_type]

        for log in receipt["logs"]:
            smart_contract = log["address"]
            if smart_contract in checked_addresses:
                continue
            checked_addresses.append(smart_contract)

            contract_object = w3.eth.contract(address=Web3.toChecksumAddress(smart_contract), abi=token_contract_abi)

            if contract_object is None:
                logging.warning(f"No ABI found for address {smart_contract}")
                continue

            # Decode any matching logs
            decoded_logs = contract_object.events[event_type]().processReceipt(receipt, errors=DISCARD)

            for decoded_log in decoded_logs:
                _log_dict[str(decoded_log["logIndex"])] = decoded_log

    return _log_dict


def get_transaction_logs(receipt: AttributeDict):
    if not isinstance(receipt, AttributeDict):
        raise ValueError(f"Type {type(receipt)} is not a legal argument for get_transaction_logs.")

    if not isinstance(receipt["blockHash"], HexBytes):
        converted_receipt = format_log_dict(receipt)
        receipt = converted_receipt

    checked_addresses = []
    _log_dict = {}

    for log in receipt["logs"]:
        smart_contract = log["address"]

        if smart_contract in checked_addresses:
            continue

        checked_addresses.append(smart_contract)
        contract_object = get_contract(address=smart_contract, block=test_block)

        if contract_object is None:
            logging.warning(f"No ABI found for address {smart_contract}")
            continue

        receipt_event_signature_hex = Web3.toHex(HexBytes(log["topics"][0]))

        abi_events = [abi for abi in contract_object.abi if abi["type"] == "event"]
        decoded_logs = []

        for event in abi_events:
            name = event["name"]
            inputs = [param["type"] for param in event["inputs"]]
            inputs = ",".join(inputs)
            # Hash event signature
            event_signature_text = f"{name}({inputs})"
            event_signature_hex = Web3.toHex(Web3.keccak(text=event_signature_text))
            # Find match between log's event signature and ABI's event signature
            if event_signature_hex == receipt_event_signature_hex:
                # Decode matching log
                # logging.info(f"Decoding log {receipt}")
                decoded_logs = contract_object.events[event["name"]]().processReceipt(receipt, errors=DISCARD)
                break

        for _processed_log in decoded_logs:
            _log_dict[str(_processed_log["logIndex"])] = _processed_log

    return _log_dict


def add_to_acc_dict(acc_dict: dict, account: str, transaction):
    if account not in acc_dict:
        acc_dict[account] = []

    acc_dict[account].append(transaction)


def transaction_balance_test(target_account: str):
    account_dict = {}

    for transaction in w3.eth.get_block_receipts(test_block):

        transaction = utils.format_log_dict(transaction)
        if not is_contract(w3.toChecksumAddress(transaction["to"])):
            continue

        block_number = transaction["blockNumber"]
        full_transaction = w3.eth.get_transaction(transaction["transactionHash"])

        if full_transaction["to"] == target_account:
            print(f"Transfer of {full_transaction['value']:,} ETH to {target_account}")

        transfer_events = get_all_events_of_type_in_tx(transaction, ["Transfer"])
        for key in sorted(transfer_events):
            transfer = transfer_events[key]
            sender = transfer['args']['from']
            receiver = transfer["args"]["to"]
            token_address = transfer['address']
            add_to_acc_dict(account_dict, sender, transfer)
            add_to_acc_dict(account_dict, receiver, transfer)

            # if sender == "0x68b3465833fb72A70ecDF485E0e4C7bD8665Fc45":
            #    total_balance -= transfer['args']['value']
            # elif receiver == "0x68b3465833fb72A70ecDF485E0e4C7bD8665Fc45":
            #    total_balance += transfer['args']['value']
            # else:
            #    continue

            if sender == target_account or receiver == target_account:
                before = get_token_balance(sender, token_address, block_number)
                print(f"Sender balance before: {before:,}")
                print(f"Transfer of {transfer['args']['value']:,} in currency {token_address} {get_contract_name_symbol(token_address)} from {sender} to {transfer['args']['to']} " +
                      f"(transaction {transfer['transactionHash'].hex()})")
                after = get_token_balance(sender, token_address, block_number + 1)
                difference = after - before
                print(f"Sender balance after: {after:,}")
                print(f"Difference: {difference:,}")
                print("")

    return


if __name__ == '__main__':
    print("")
    logging.info("************ Starting **************")

    # setup web3
    w3_local = Web3(local_provider)
    w3_remote = Web3(remote_provider)

    # PICK WEB3 PROVIDER
    w3 = w3_local

    # read database location from config and open it
    database = db.Database(parameters["Database"])

    # get the latest block and log it
    latest_block = w3.eth.get_block_number()
    logging.info(f"Latest block: {latest_block}.")

    # example block and transaction
    test_block = 14394958
    test_tx = "0x7435b60090e0347fc09bb961e02a4dd5baa59ce0ed83de2f0dffca36243d66f9"

    # ********* TESTING *************

    # transaction_balance_test('0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D')
    # more balance test accounts
    '0x220bdA5c8994804Ac96ebe4DF184d25e5c2196D4'
    '0x1111111254fb6c44bAC0beD2854e76F90643097d'

    print(get_abi("0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2", 0))

    shutdown()

    # ------------------ INACTIVE CODE --------------------------

    for tx in w3.eth.get_block_receipts(test_block):
        if tx["logs"]:
            converted_transaction = utils.format_log_dict(tx)
            log_dict = get_all_events_of_type_in_tx(converted_transaction, ["Swap", "Transfer"])
            if log_dict:
                print(f"Transaction: {converted_transaction['transactionHash'].hex()}")
                print(f"From: \t\t{converted_transaction['from']}")
                print(f"To: \t\t{converted_transaction['to']}")
                for key in log_dict:
                    if log_dict[key]["event"] == "Transfer":
                        print("Transfer")
                        print(f"Sender: \t{log_dict[key]['args']['from']}")
                        print(f"Amount: \t{log_dict[key]['args']['value']}")
                    elif log_dict[key]["event"] == "Swap":
                        print("Swap")
                        print(f"Sender: \t{log_dict[key]['args']['sender']}")
                        print(
                            f"amount0in: {log_dict[key]['args']['amount0In']}, amount1in: {log_dict[key]['args']['amount1In']}, amount0out: {log_dict[key]['args']['amount0Out']}, amount1out: {log_dict[key]['args']['amount1Out']}")
                    print(f"Receiver: \t{log_dict[key]['args']['to']}")

                    print("")
            break
