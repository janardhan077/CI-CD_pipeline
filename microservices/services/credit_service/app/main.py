"""
Credit service. Owns `customers` (master data) and `credit_payments`.
"""
import datetime as dt
import logging

from fastapi import FastAPI, Depends
from sqlalchemy.orm import Session

from common.config import get_settings
from common.database import get_db, init_db
from common.errors import register_error_handlers

from app.schemas import (
    CustomerCreate, CustomerOut, CreditPaymentCreate, CreditPaymentOut, CustomerBalanceOut,
)
from app.service import CreditService

settings = get_settings()
logging.basicConfig(level=settings.log_level)

app = FastAPI(title="IN-ON Credit Service", version="0.1.0")
register_error_handlers(app)


@app.on_event("startup")
def on_startup():
    init_db()


@app.get("/health")
def health():
    return {"status": "ok", "service": "credit-service"}


@app.post("/customers", response_model=CustomerOut, status_code=201)
def create_customer(payload: CustomerCreate, db: Session = Depends(get_db)):
    return CreditService(db).create_customer(**payload.model_dump())


@app.get("/customers", response_model=list[CustomerOut])
def list_customers(db: Session = Depends(get_db)):
    return CreditService(db).list_customers()


@app.get("/customers/credit/outstanding", response_model=list[CustomerBalanceOut])
def all_outstanding(as_of: dt.date | None = None, db: Session = Depends(get_db)):
    return CreditService(db).get_all_outstanding(as_of=as_of)


@app.get("/customers/{customer_id}/balance", response_model=CustomerBalanceOut)
def get_balance(customer_id: int, db: Session = Depends(get_db)):
    service = CreditService(db)
    customer = service.get_customer(customer_id)
    return {
        "customer_id": customer_id,
        "name": customer.name,
        "outstanding": service.get_outstanding(customer_id),
    }


@app.post("/customers/{customer_id}/payments", response_model=CreditPaymentOut, status_code=201)
def record_payment(customer_id: int, payload: CreditPaymentCreate, db: Session = Depends(get_db)):
    service = CreditService(db)
    data = payload.model_dump()
    payment = service.record_payment(customer_id=customer_id, **data)
    return {"id": payment.id, "amount": float(payment.amount)}
