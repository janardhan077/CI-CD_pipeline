import datetime as dt

from pydantic import BaseModel, Field, ConfigDict

from common.core.enums import PaymentMethod, ActorType


class ExpenseCategoryCreate(BaseModel):
    name: str


class ExpenseCategoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str


class ExpenseCreate(BaseModel):
    expense_date: dt.date
    category_id: int
    amount: float = Field(gt=0)
    payment_method: PaymentMethod = PaymentMethod.CASH
    description: str | None = None
    notes: str | None = None
    created_by: ActorType = ActorType.USER


class ExpenseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    expense_date: dt.date
    category_id: int
    amount: float
    payment_method: PaymentMethod
    description: str | None


class ExpenseListItemOut(BaseModel):
    id: int
    expense_date: dt.date
    category_id: int
    category_name: str
    amount: float
    payment_method: PaymentMethod
    description: str | None


class CorrectExpenseRequest(BaseModel):
    new_amount: float | None = Field(default=None, gt=0)
    new_category_id: int | None = None
    new_payment_method: PaymentMethod | None = None
    new_description: str | None = None
    reason: str = "Corrected via assistant"
    created_by: ActorType = ActorType.USER


class CorrectExpenseResponse(BaseModel):
    old_expense_id: int
    old_amount: float
    new_expense_id: int
    new_amount: float


class ExpenseBreakdownOut(BaseModel):
    category: str
    amount: float
