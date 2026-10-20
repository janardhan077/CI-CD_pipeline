import datetime as dt

from pydantic import BaseModel, Field, ConfigDict

from common.core.enums import PaymentMethod, ActorType


class StockTypeCreate(BaseModel):
    name: str
    unit: str = "bag"


class StockTypeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    unit: str
    last_physical_count_date: dt.date | None


class PurchaseCreate(BaseModel):
    purchase_date: dt.date
    stock_type_id: int
    quantity: float = Field(gt=0)
    rate: float = Field(ge=0)
    amount_paid: float | None = None
    supplier_id: int | None = None
    payment_method: PaymentMethod = PaymentMethod.CASH
    notes: str | None = None
    created_by: ActorType = ActorType.USER


class PurchaseOut(BaseModel):
    id: int
    total_amount: float


class StockAdjustmentCreate(BaseModel):
    adjustment_date: dt.date
    stock_type_id: int
    quantity_delta: float
    reason: str
    notes: str | None = None
    created_by: ActorType = ActorType.USER


class StockAdjustmentOut(BaseModel):
    id: int


class StockSnapshotOut(BaseModel):
    stock_type_id: int
    name: str
    unit: str
    quantity: float
    last_physical_count_date: dt.date | None
