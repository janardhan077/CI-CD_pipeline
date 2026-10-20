"""
CashBank service. Owns no table of its own - see app/service.py.
"""
import datetime as dt
import logging

from fastapi import FastAPI

from common.config import get_settings
from common.core.enums import Direction
from common.errors import register_error_handlers

from app.schemas import CashBankAdjustCreate, BalancesOut, LedgerRefOut, TransferOut
from app.service import CashBankService

settings = get_settings()
logging.basicConfig(level=settings.log_level)

app = FastAPI(title="IN-ON CashBank Service", version="0.1.0")
register_error_handlers(app)


@app.get("/health")
def health():
    return {"status": "ok", "service": "cashbank-service"}


@app.get("/cashbank/balances", response_model=BalancesOut)
def get_balances(as_of: dt.date | None = None):
    return CashBankService().get_balances(as_of=as_of)


@app.post("/cashbank/cash/in", response_model=LedgerRefOut, status_code=201)
def cash_in(payload: CashBankAdjustCreate):
    txn = CashBankService().adjust_cash(direction=Direction.IN, **payload.model_dump())
    return {"id": txn["id"]}


@app.post("/cashbank/cash/out", response_model=LedgerRefOut, status_code=201)
def cash_out(payload: CashBankAdjustCreate):
    txn = CashBankService().adjust_cash(direction=Direction.OUT, **payload.model_dump())
    return {"id": txn["id"]}


@app.post("/cashbank/bank/in", response_model=LedgerRefOut, status_code=201)
def bank_in(payload: CashBankAdjustCreate):
    txn = CashBankService().adjust_bank(direction=Direction.IN, **payload.model_dump())
    return {"id": txn["id"]}


@app.post("/cashbank/bank/out", response_model=LedgerRefOut, status_code=201)
def bank_out(payload: CashBankAdjustCreate):
    txn = CashBankService().adjust_bank(direction=Direction.OUT, **payload.model_dump())
    return {"id": txn["id"]}


@app.post("/cashbank/transfer-to-bank", response_model=TransferOut, status_code=201)
def transfer_to_bank(payload: CashBankAdjustCreate):
    cash_out_txn, bank_in_txn = CashBankService().transfer_cash_to_bank(**payload.model_dump())
    return {"cash_out_id": cash_out_txn["id"], "bank_in_id": bank_in_txn["id"]}
