from __future__ import annotations

from app.db import _begin


class _Conn:
    def __init__(self, write: bool) -> None:
        self.info = {"pc_write_txn": write}
        self.statements: list[str] = []

    def exec_driver_sql(self, statement: str) -> None:
        self.statements.append(statement)


def test_read_transaction_does_not_take_immediate_lock() -> None:
    conn = _Conn(write=False)

    _begin(conn)

    assert conn.statements == ["BEGIN"]


def test_write_transaction_takes_immediate_lock() -> None:
    conn = _Conn(write=True)

    _begin(conn)

    assert conn.statements == ["BEGIN IMMEDIATE"]
