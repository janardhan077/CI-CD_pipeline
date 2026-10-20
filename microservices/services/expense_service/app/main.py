"""
Expense service. Owns `expenses` and `expense_categories`.
"""
import datetime as dt
import logging

from fastapi import FastAPI, Depends, Query
from sqlalchemy.orm import Session

from common.config import get_settings
from common.database import get_db, init_db
from common.errors import register_error_handlers

from app.schemas import (
    ExpenseCreate, ExpenseOut, ExpenseCategoryCreate, ExpenseCategoryOut, ExpenseBreakdownOut,
    ExpenseListItemOut, CorrectExpenseRequest, CorrectExpenseResponse,
)
from app.service import ExpenseService

settings = get_settings()
logging.basicConfig(level=settings.log_level)

app = FastAPI(title="IN-ON Expense Service", version="0.1.0")
register_error_handlers(app)


@app.on_event("startup")
def on_startup():
    init_db()


@app.get("/health")
def health():
    return {"status": "ok", "service": "expense-service"}


@app.post("/expenses", response_model=ExpenseOut, status_code=201)
def create_expense(payload: ExpenseCreate, db: Session = Depends(get_db)):
    return ExpenseService(db).record_expense(**payload.model_dump())


@app.get("/expenses", response_model=list[ExpenseListItemOut])
def list_expenses(
    expense_date: dt.date | None = None, category_id: int | None = None, db: Session = Depends(get_db)
):
    """Read-only - used by the Assistant service to find a specific
    expense the owner wants to correct ("update_expense" intent)."""
    expenses = ExpenseService(db).list_expenses(expense_date=expense_date, category_id=category_id)
    return [
        {
            "id": e.id, "expense_date": e.expense_date, "category_id": e.category_id,
            "category_name": e.category.name if e.category else "Uncategorized",
            "amount": float(e.amount), "payment_method": e.payment_method,
            "description": e.description,
        }
        for e in expenses
    ]


@app.post("/expenses/categories", response_model=ExpenseCategoryOut, status_code=201)
def create_category(payload: ExpenseCategoryCreate, db: Session = Depends(get_db)):
    return ExpenseService(db).create_category(**payload.model_dump())


@app.get("/expenses/categories", response_model=list[ExpenseCategoryOut])
def list_categories(db: Session = Depends(get_db)):
    return ExpenseService(db).list_categories()


@app.get("/expenses/total")
def total_between(start: dt.date = Query(...), end: dt.date = Query(...), db: Session = Depends(get_db)):
    return {"total": ExpenseService(db).total_between(start, end)}


@app.get("/expenses/breakdown", response_model=list[ExpenseBreakdownOut])
def breakdown_between(start: dt.date = Query(...), end: dt.date = Query(...), db: Session = Depends(get_db)):
    return ExpenseService(db).breakdown_between(start, end)


@app.post("/expenses/{expense_id}/correct", response_model=CorrectExpenseResponse, status_code=201)
def correct_expense(expense_id: int, payload: CorrectExpenseRequest, db: Session = Depends(get_db)):
    """Never edits a row in place - voids the original, reverses its
    ledger effect, and records a fresh corrected expense. See
    ExpenseService.correct_expense's docstring."""
    old, new = ExpenseService(db).correct_expense(expense_id, **payload.model_dump())
    return {
        "old_expense_id": old.id, "old_amount": float(old.amount),
        "new_expense_id": new.id, "new_amount": float(new.amount),
    }
