"""
Stock service. Owns `stock_types`, `purchases`, and `stock_adjustments`.
"""
import datetime as dt
import logging

from fastapi import FastAPI, Depends
from sqlalchemy.orm import Session

from common.config import get_settings
from common.database import get_db, init_db
from common.errors import register_error_handlers

from app.schemas import (
    StockTypeCreate, StockTypeOut, PurchaseCreate, PurchaseOut,
    StockAdjustmentCreate, StockAdjustmentOut, StockSnapshotOut,
)
from app.service import StockService

settings = get_settings()
logging.basicConfig(level=settings.log_level)

app = FastAPI(title="IN-ON Stock Service", version="0.1.0")
register_error_handlers(app)


@app.on_event("startup")
def on_startup():
    init_db()


@app.get("/health")
def health():
    return {"status": "ok", "service": "stock-service"}


@app.post("/stock/types", response_model=StockTypeOut, status_code=201)
def create_stock_type(payload: StockTypeCreate, db: Session = Depends(get_db)):
    return StockService(db).create_stock_type(**payload.model_dump())


@app.get("/stock/types", response_model=list[StockTypeOut])
def list_stock_types(db: Session = Depends(get_db)):
    return StockService(db).list_stock_types()


@app.post("/stock/purchases", response_model=PurchaseOut, status_code=201)
def create_purchase(payload: PurchaseCreate, db: Session = Depends(get_db)):
    purchase = StockService(db).record_purchase(**payload.model_dump())
    return {"id": purchase.id, "total_amount": float(purchase.total_amount)}


@app.post("/stock/adjustments", response_model=StockAdjustmentOut, status_code=201)
def create_adjustment(payload: StockAdjustmentCreate, db: Session = Depends(get_db)):
    adjustment = StockService(db).record_adjustment(**payload.model_dump())
    return {"id": adjustment.id}


@app.get("/stock/snapshot", response_model=list[StockSnapshotOut])
def stock_snapshot(as_of: dt.date | None = None, db: Session = Depends(get_db)):
    return StockService(db).get_stock_snapshot(as_of=as_of)
