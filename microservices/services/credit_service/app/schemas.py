import datetime as dt

from pydantic import BaseModel, Field, ConfigDict

from common.core.enums import PaymentMethod, ActorType


class CustomerCreate(BaseModel):
    name: str
    phone: str | None = None
    disambiguator: str | None = None
    opening_balance: float = 0
    opening_balance_date: dt.date | None = None


class CustomerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    phone: str | None
    disambiguator: str | None
    is_active: bool


class CreditPaymentCreate(BaseModel):
    payment_date: dt.date
    amount: float = Field(gt=0)
    payment_method: PaymentMethod = PaymentMethod.CASH
    notes: str | None = None
    allow_overpayment: bool = False
    created_by: ActorType = ActorType.USER


class CreditPaymentOut(BaseModel):
    id: int
    amount: float


class CustomerBalanceOut(BaseModel):
    customer_id: int
    name: str
    outstanding: float
