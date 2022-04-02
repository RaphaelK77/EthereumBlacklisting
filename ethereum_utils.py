import logging

import web3.exceptions
from web3 import Web3


class EthereumUtils:
    def __init__(self, w3: Web3):
        self.w3 = w3

    def get_token_balance(self, account: str, token_address: str, block: int = None):
        """
        Retrieves the token balance of the given account at the given block

        :param account: Ethereum account
        :param token_address: Ethereum address of token
        :param block: block to be executed at
        :return: token balance, -1 if it cannot be retrieved
        """

        if block is None:
            block = self.w3.eth.get_block_number()

        token_contract_abi = [
            {"type": "function", "name": "balanceOf", "constant": "true", "payable": "false", "inputs": [{"name": "", "type": "address"}], "outputs": [{"name": "", "type": "uint256"}]}]

        contract = self.w3.eth.contract(address=Web3.toChecksumAddress(token_address), abi=token_contract_abi)

        try:
            balance = contract.functions.balanceOf(account).call({}, block)
        except web3.exceptions.BadFunctionCallOutput:
            logging.warning(f"BalanceOf function for token smart contract at {token_address} could not be executed.")
            balance = -1

        return balance
