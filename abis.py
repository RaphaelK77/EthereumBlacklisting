event_abis = {
    "Transfer": [{
        'anonymous': False,
        'inputs': [{'indexed': True, 'name': 'from', 'type': 'address'},
                   {'indexed': True, 'name': 'to', 'type': 'address'},
                   {'indexed': False, 'name': 'value', 'type': 'uint256'}],
        'name': 'Transfer',
        'type': 'event'
    }],
    "Swap": [{
        'anonymous': False,
        'inputs': [{'indexed': True, 'internalType': 'address', 'name': 'sender', 'type': 'address'},
                   {'indexed': False, 'internalType': 'uint256', 'name': 'amount0In', 'type': 'uint256'},
                   {'indexed': False, 'internalType': 'uint256', 'name': 'amount1In', 'type': 'uint256'},
                   {'indexed': False, 'internalType': 'uint256', 'name': 'amount0Out', 'type': 'uint256'},
                   {'indexed': False, 'internalType': 'uint256', 'name': 'amount1Out', 'type': 'uint256'},
                   {'indexed': True, 'internalType': 'address', 'name': 'to', 'type': 'address'}],
        'name': 'Swap',
        'type': 'event'
    }],
    "Deposit": [{
        "anonymous": False,
        "inputs":
            [{"indexed": True, "name": "dst", "type": "address"},
             {"indexed": False, "name": "wad", "type": "uint256"}],
        "name": "Deposit",
        "type": "event"
    }],
    "Withdrawal": [{
        "anonymous": False,
        "inputs":
            [{"indexed": True, "name": "src", "type": "address"},
             {"indexed": False, "name": "wad", "type": "uint256"}],
        "name": "Withdrawal",
        "type": "event"
    }]}

function_abis = {
    "Name": [{
        "constant": True,
        "inputs": [],
        "name": "name",
        "outputs": [{
            "name": "",
            "type": "string"
        }],
        "payable": False,
        "stateMutability": "view",
        "type": "function"
    }],
    "Symbol": [{
        "constant": True,
        "inputs": [],
        "name": "symbol",
        "outputs": [{
            "name": "",
            "type": "string"
        }],
        "payable": False,
        "stateMutability": "view",
        "type": "function"
    }],
    "Tokens": [{
        "inputs": [],
        "name": "token0",
        "outputs": [{
            "internalType": "address",
            "name": "",
            "type": "address"
        }],
        "stateMutability": "view",
        "type": "function"
    }, {
        "inputs": [],
        "name": "token1",
        "outputs": [{
            "internalType": "address",
            "name": "",
            "type": "address"
        }],
        "stateMutability": "view",
        "type": "function"
    }],
    "BalanceOf": [{
        "type": "function",
        "name": "balanceOf",
        "constant": "true",
        "payable": "false",
        "inputs": [{
            "name": "",
            "type": "address"}],
        "outputs": [{
            "name": "",
            "type": "uint256"}]
    }]
}

topics = {
    "Deposit": "0xe1fffcc4923d04b559f4d29a8bfc6cda04eb5b0d3c460751c2402c5c5cc9109c",
    "Transfer": "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef",
    "Withdrawal": "0x7fcf532c15f0a6db0bd6d0e038bea71d30d808c7d98cb3bf7268a95bf5081b65"
}
