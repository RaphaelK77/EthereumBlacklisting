import time

from hexbytes import HexBytes
from web3.datastructures import AttributeDict


def format_seconds_as_time(seconds):
    return time.strftime('%H:%M:%S', time.gmtime(seconds))


def format_log_dict(log_dict: AttributeDict) -> AttributeDict:
    result_dict = {}

    for hex_key in ["blockHash", "transactionHash"]:
        result_dict[hex_key] = HexBytes(log_dict[hex_key])
    for int_key in ["blockNumber", "cumulativeGasUsed", "effectiveGasPrice", "gasUsed", "status", "transactionIndex"]:
        result_dict[int_key] = int(log_dict[int_key], base=16)
    for str_key in ["contractAddress", "from", "logsBloom", "to", "type"]:
        result_dict[str_key] = str(log_dict[str_key])

    result_dict["logs"] = []
    for log in log_dict["logs"]:
        result_log = {}
        for hex_key in ["transactionHash", "blockHash"]:
            result_log[hex_key] = HexBytes(log[hex_key])
        for int_key in ["blockNumber", "logIndex", "transactionIndex"]:
            result_log[int_key] = int(log[int_key], base=16)
        # also includes bool value, so no cast
        for str_key in ["address", "data", "removed"]:
            result_log[str_key] = log[str_key]

        result_log["topics"] = [HexBytes(topic) for topic in log["topics"]]
        result_dict["logs"].append(result_log)

    return AttributeDict(result_dict)
