import datetime as dt

from pydantic import BaseModel, Field


class CashBankAdjustCreate(BaseModel):
    date: dt.date
    amount: float = Field(gt=0)
    reason: str


class BalancesOut(BaseModel):
    cash: float
    bank: float


class LedgerRefOut(BaseModel):
    id: int


class TransferOut(BaseModel):
    cash_out_id: int
    bank_in_id: int
