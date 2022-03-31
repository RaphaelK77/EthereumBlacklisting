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
    "Name+Symbol": [{
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
    }, {
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
}
