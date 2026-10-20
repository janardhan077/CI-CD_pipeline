import datetime as dt

from pydantic import BaseModel, ConfigDict

from common.core.enums import TxnType, Account, Direction, ActorType


class PostTransactionRequest(BaseModel):
    txn_datetime: dt.datetime
    txn_type: TxnType
    account: Account
    direction: Direction
    amount: float
    customer_id: int | None = None
    supplier_id: int | None = None
    stock_type_id: int | None = None
    reference_table: str | None = None
    reference_id: int | None = None
    description: str | None = None
    created_by: ActorType = ActorType.USER


class ReverseTransactionRequest(BaseModel):
    reason: str
    created_by: ActorType = ActorType.USER


class LedgerTransactionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    txn_datetime: dt.datetime
    txn_type: TxnType
    account: Account
    direction: Direction
    amount: float
    customer_id: int | None
    supplier_id: int | None
    stock_type_id: int | None
    reference_table: str | None
    reference_id: int | None
    reverses_txn_id: int | None
    description: str | None
    created_by: ActorType


class BalanceOut(BaseModel):
    balance: float
