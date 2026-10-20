"""
Ledger service.

Run with: uvicorn app.main:app --port 8000
(each service listens on 8000 *inside* its own container; docker-compose
maps distinct host ports - see the top-level docker-compose.yml.)

THIS IS THE ONLY SERVICE ALLOWED TO WRITE TO ledger_transactions.
Every other service reaches this one over HTTP via
common.ledger_client.LedgerClient - see that module's docstring for why
a shared database does not mean a shared transaction, and what each
caller does about it.
"""
import datetime as dt
import logging

from fastapi import FastAPI, Depends, Query
from sqlalchemy.orm import Session

from common.config import get_settings
from common.core.enums import Account
from common.database import get_db, init_db
from common.errors import register_error_handlers

from app.schemas import PostTransactionRequest, ReverseTransactionRequest, LedgerTransactionOut, BalanceOut
from app.service import LedgerService

settings = get_settings()
logging.basicConfig(level=settings.log_level)

app = FastAPI(title="IN-ON Ledger Service", version="0.1.0")
register_error_handlers(app)


@app.on_event("startup")
def on_startup():
    init_db()


@app.get("/health")
def health():
    return {"status": "ok", "service": "ledger-service"}


@app.post("/transactions", response_model=LedgerTransactionOut, status_code=201)
def post_transaction(payload: PostTransactionRequest, db: Session = Depends(get_db)):
    service = LedgerService(db)
    return service.post_transaction(**payload.model_dump())


@app.post("/transactions/{transaction_id}/reverse", response_model=LedgerTransactionOut, status_code=201)
def reverse_transaction(transaction_id: int, payload: ReverseTransactionRequest, db: Session = Depends(get_db)):
    service = LedgerService(db)
    return service.reverse_transaction(transaction_id, **payload.model_dump())


@app.get("/balances/cash", response_model=BalanceOut)
def cash_balance(as_of: dt.date | None = None, db: Session = Depends(get_db)):
    return {"balance": LedgerService(db).get_cash_balance(as_of=as_of)}


@app.get("/balances/bank", response_model=BalanceOut)
def bank_balance(as_of: dt.date | None = None, db: Session = Depends(get_db)):
    return {"balance": LedgerService(db).get_bank_balance(as_of=as_of)}


@app.get("/balances/stock", response_model=BalanceOut)
def total_stock(as_of: dt.date | None = None, db: Session = Depends(get_db)):
    return {"balance": LedgerService(db).get_total_stock(as_of=as_of)}


@app.get("/balances/stock/{stock_type_id}", response_model=BalanceOut)
def stock_by_type(stock_type_id: int, as_of: dt.date | None = None, db: Session = Depends(get_db)):
    return {"balance": LedgerService(db).get_stock_by_type(stock_type_id, as_of=as_of)}


@app.get("/balances/customer/{customer_id}", response_model=BalanceOut)
def customer_outstanding(customer_id: int, as_of: dt.date | None = None, db: Session = Depends(get_db)):
    return {"balance": LedgerService(db).get_customer_outstanding(customer_id, as_of=as_of)}


@app.get("/transactions", response_model=list[LedgerTransactionOut])
def transactions_for(reference_table: str = Query(...), reference_id: int = Query(...), db: Session = Depends(get_db)):
    return LedgerService(db).get_transactions_for(reference_table=reference_table, reference_id=reference_id)


@app.get("/transactions/between", response_model=list[LedgerTransactionOut])
def transactions_between(
    start: dt.date, end: dt.date, account: Account | None = None, db: Session = Depends(get_db)
):
    return LedgerService(db).get_transactions_between(start, end, account=account)


@app.get("/transactions/{transaction_id}", response_model=LedgerTransactionOut)
def get_transaction(transaction_id: int, db: Session = Depends(get_db)):
    return LedgerService(db).get_transaction(transaction_id)
