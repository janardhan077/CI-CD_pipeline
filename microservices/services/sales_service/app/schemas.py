import datetime as dt

from pydantic import BaseModel, Field, ConfigDict

from common.core.enums import PaymentMethod, ActorType


class SaleCreate(BaseModel):
    sale_date: dt.date
    customer_id: int
    stock_type_id: int
    quantity: float = Field(gt=0)
    rate: float = Field(ge=0)
    cash_received: float = Field(default=0, ge=0)
    bank_received: float = Field(default=0, ge=0)
    unit: str = "bag"
    notes: str | None = None
    allow_negative_stock: bool = False
    created_by: ActorType = ActorType.USER


class SaleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    sale_date: dt.date
    customer_id: int
    stock_type_id: int
    quantity: float
    rate: float
    total_amount: float
    cash_received: float
    bank_received: float
    amount_received: float
    credit_amount: float
    payment_method: PaymentMethod
