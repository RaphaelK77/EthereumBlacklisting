import datetime
import logging
import sqlite3

from typing import Optional


class Database:
    def __init__(self, database_path):
        self.database = sqlite3.connect(database_path)
        self.cursor = self.database.cursor()

    def save_log(self, level: str, time: datetime.datetime, transaction: str, event: str, from_account: Optional[str], to_account: Optional[str], amount: int, currency: str,
                 amount_2: Optional[int] = None):
        code = """
                INSERT INTO log (level, time, tx, event, from_account, to_account, amount, currency, amount_2)
                VALUES (:level, :time, :tx, :event, :from_account, :to_account, :amount, :currency, :amount_2)
                """
        self.cursor.execute(code, {"level": level, "time": str(time), "event": event, "tx": transaction, "amount_2": str(amount_2),
                                   "from_account": from_account, "to_account": to_account, "amount": str(amount), "currency": currency})
        self.database.commit()

    def clear_logs(self):
        code = "DELETE FROM log"
        self.cursor.execute(code)
        self.database.commit()

    def add_contract(self, address: str, abi: str, block: int):
        code = f"""INSERT INTO contracts (address, abi, last_access)
                VALUES (:address, :abi, :block)
                """
        self.cursor.execute(code, {"address": address, "abi": abi, "block": block})
        self.database.commit()
        logging.debug(f"Added contract address '{address}' to self.database.")

    def get_abi(self, address: str, block: int):
        code = f"""SELECT abi FROM contracts
            WHERE address = :address"""
        result = self.cursor.execute(code, {"address": address}).fetchall()
        logging.debug(f"Retrieved ABI {result} for address {address}")
        if not result:
            return result
        self.record_access(address, block)
        return result[0][0]

    def set_name_symbol(self, address: str, name: str, symbol: str = None):
        code = """UPDATE contracts
                SET name = :name, symbol = :symbol
                WHERE address = :address"""
        self.cursor.execute(code, {"address": address, "name": name, "symbol": symbol})
        logging.debug(f"Set name '{name}', symbol '{symbol}' for contract '{address}'.")
        self.database.commit()

    def record_access(self, address: str, block: int):
        code = """UPDATE contracts
                SET accesses = accesses + 1,
                last_access = :block
                WHERE address = :address"""
        self.cursor.execute(code, {"address": address, "block": block})
        self.database.commit()

    def get_name_symbol(self, address: str, block: int):
        code = """SELECT name, symbol
                FROM contracts
                WHERE address = :address"""
        result = self.cursor.execute(code, {"address": address}).fetchall()
        if not result:
            return []
        self.record_access(address, block)
        name = result[0][0]
        symbol = result[0][1]
        logging.debug(f"Retrieved name '{name}', symbol '{symbol}' for address '{address}' from db.")
        return name, symbol

    def reset_accesses(self):
        code = """UPDATE contracts
            SET accesses = 0,
            last_access = 0"""
        self.cursor.execute(code)
        self.database.commit()

    def cleanup(self):
        self.reset_accesses()
        self.database.close()
