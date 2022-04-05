import logging
import signal
import subprocess
import sys
import time

from web3 import Web3

START_BLOCK_MARGIN = 1000
END_BLOCK_MARGIN = 1000

MAX_SYNC_WAIT_TIME = 600  # in seconds
HANDLER_POLL_TIME = 30  # seconds

RPC_ONLY = True

DATA_DIR = "A:\\Ethereum"

data_file = "E:\\Ethereum\\download_data\\download_data_erigon.csv"


def shutdown(proc):
    proc.send_signal(signal.CTRL_C_EVENT)
    try:
        proc.wait()
    except KeyboardInterrupt:
        proc.wait()


def wait_until_sync(w3):
    logging.info("Waiting while node is starting...")
    max_loops = int(MAX_SYNC_WAIT_TIME / 10)
    for i in range(max_loops):
        time.sleep(10)
        syncing = w3.eth.syncing
        if syncing:
            logging.info("Waiting complete, node is syncing.")
            return syncing
    logging.warning("Waited for the maximum amount of time, but node has not started syncing.")
    return False


def wait_for_pipe(max_attempts):
    for i in range(max_attempts):
        try:
            time.sleep(10)
            local_provider = Web3.HTTPProvider()  # "\\\\.\\pipe\\geth.ipc"
            w3 = Web3(local_provider)
            try:
                _ = w3.eth.syncing
            except Exception as e:
                logging.warning(f"Exception '{e}' when trying to open provider")
                continue
            logging.info("IPC opened successfully.")
            return w3
        except FileNotFoundError:
            continue
    return None


def start_rpc_daemon():
    return subprocess.Popen(["rpcdaemon", f"--datadir={DATA_DIR}", "--private.api.addr=localhost:9090", "--http.api=eth,erigon,web3,net,debug,trace,txpool"], shell=True)


def start_node_process(start_block: int):
    args = ["erigon", f"--datadir={DATA_DIR}", "--prune=hrtc", f"--prune.h.before={start_block}", f"--prune.r.before={start_block}", f"--prune.t.before={start_block}",
            f"--prune.c.before={start_block}", "--nodiscover"]

    return subprocess.Popen(args, shell=True)


def start_node(start_block):
    logging.info("Starting node in subprocess...")

    if not RPC_ONLY:
        proc = start_node_process(start_block)
    daemon = start_rpc_daemon()

    try:
        while True:
            time.sleep(5)
    except KeyboardInterrupt:
        logging.info(f"Keyboard interrupt detected. Shutting down.")
        if not RPC_ONLY:
            shutdown(proc)
        shutdown(daemon)
        logging.info("Subprocess has terminated. Exiting.")
        exit(0)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        logging.error("Usage: node_process_handler.py [start_block]")
        exit(-1)
    start_block_arg = int(sys.argv[1])
    logging.info(f"Starting node with start block {start_block_arg:,}.")
    start_node(start_block_arg)
