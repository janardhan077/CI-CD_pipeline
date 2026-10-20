"""
Sales service. Owns the `sales` table. Talks to the Ledger service
over HTTP for every ledger-affecting side effect of a sale - see
app/service.py's docstring for the consistency model.
"""
import datetime as dt
import logging

from fastapi import FastAPI, Depends
from sqlalchemy.orm import Session

from common.config import get_settings
from common.database import get_db, init_db
from common.errors import register_error_handlers

from app.schemas import SaleCreate, SaleOut
from app.service import SalesService

settings = get_settings()
logging.basicConfig(level=settings.log_level)

app = FastAPI(title="IN-ON Sales Service", version="0.1.0")
register_error_handlers(app)


@app.on_event("startup")
def on_startup():
    init_db()


@app.get("/health")
def health():
    return {"status": "ok", "service": "sales-service"}


@app.post("/sales", response_model=SaleOut, status_code=201)
def create_sale(payload: SaleCreate, db: Session = Depends(get_db)):
    service = SalesService(db)
    return service.record_sale(**payload.model_dump())


@app.get("/sales", response_model=list[SaleOut])
def list_sales(sale_date: dt.date | None = None, db: Session = Depends(get_db)):
    """Read-only - used by the Report and Assistant services. Neither
    of them holds a database connection of its own; this is the only
    way they see sales data."""
    return SalesService(db).list_sales(sale_date=sale_date)
