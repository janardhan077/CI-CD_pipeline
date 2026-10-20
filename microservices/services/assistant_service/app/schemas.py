"""
The intent contract.

This is the ENTIRE surface area the AI is allowed to communicate
through. Ollama never sees a database connection, SQL, or even a
service's internal models - it produces one of these structured
objects, and app/dispatcher.py is the only code that turns an Intent
into an HTTP call to another service.

`action` is a closed enum. If the model's raw JSON contains an action
outside this set, or malformed fields, Pydantic validation fails and
the dispatcher treats it as "could not understand" rather than
guessing - per the project's AI safety rules ("never invent
transactions", "never guess missing financial values").
"""
import datetime as dt
import enum

from pydantic import BaseModel, Field


class IntentAction(str, enum.Enum):
    # Writes - go through normal service validation, no special
    # confirmation needed (they're additive, not destructive).
    RECORD_SALE = "record_sale"
    RECORD_EXPENSE = "record_expense"
    RECORD_CREDIT_PAYMENT = "record_credit_payment"
    RECORD_PURCHASE = "record_purchase"
    RECORD_STOCK_ADJUSTMENT = "record_stock_adjustment"

    # Reads - always safe, never need confirmation.
    QUERY_STOCK = "query_stock"
    QUERY_CUSTOMER_CREDIT = "query_customer_credit"
    QUERY_TOTAL_CREDIT = "query_total_credit"
    QUERY_SALES_TOTAL = "query_sales_total"
    QUERY_EXPENSE_TOTAL = "query_expense_total"
    GENERATE_REPORT = "generate_report"

    # Destructive / correcting - ALWAYS require an explicit confirm
    # step. Never executed on first pass.
    REVERSE_TRANSACTION = "reverse_transaction"
    UPDATE_EXPENSE = "update_expense"

    # General-purpose - answered conversationally, NEVER writes
    # anything. Calculations, predictions/estimates grounded in real
    # recent data, and any other business-relevant question that
    # isn't one of the specific actions above.
    GENERAL_QUERY = "general_query"

    # Meta
    CLARIFY = "clarify"          # the model needs more info from the user
    UNSUPPORTED = "unsupported"  # request is outside IN-ON's scope entirely


class Intent(BaseModel):
    action: IntentAction
    confidence_note: str | None = Field(
        default=None, description="Optional short note on why the model chose this action"
    )

    # --- entity references, resolved by NAME (the AI never sees IDs) ---
    customer_name: str | None = None
    stock_type_name: str | None = None
    supplier_name: str | None = None
    expense_category_name: str | None = None

    # --- common numeric/date fields, all optional - presence depends on action ---
    date: dt.date | None = None
    quantity: float | None = None
    rate: float | None = None
    total_amount: float | None = None
    cash_received: float | None = None
    bank_received: float | None = None
    amount: float | None = None          # generic amount (expense, credit payment, adjustment)
    reason: str | None = None            # for adjustments / reversals
    notes: str | None = None

    # --- meta fields ---
    clarifying_question: str | None = None   # populated when action == CLARIFY
    reference_transaction_id: int | None = None  # for REVERSE_TRANSACTION
    raw_user_message: str | None = None


class ChatRequest(BaseModel):
    message: str
    intent: Intent | None = None    # present when confirming a previously-described action
    confirmed: bool = False


class ChatResponse(BaseModel):
    status: str
    message: str
    intent: Intent | None = None
    data: dict = {}
