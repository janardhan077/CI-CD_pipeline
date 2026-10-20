"""
Enumerations shared across the whole application.

Keeping these centralized avoids "magic strings" scattered through
models, services, and the AI intent layer.
"""
import enum


class TxnType(str, enum.Enum):
    """Every possible entry in the ledger. This is the closed set of
    things that are allowed to change a balance in IN-ON."""
    SALE_CASH = "SALE_CASH"
    SALE_CREDIT = "SALE_CREDIT"          # the credit portion of a part-paid sale
    CREDIT_PAYMENT = "CREDIT_PAYMENT"    # customer paying down existing credit
    EXPENSE = "EXPENSE"
    PURCHASE = "PURCHASE"
    CASH_IN = "CASH_IN"
    CASH_OUT = "CASH_OUT"
    BANK_IN = "BANK_IN"
    BANK_OUT = "BANK_OUT"
    STOCK_IN = "STOCK_IN"
    STOCK_OUT = "STOCK_OUT"
    STOCK_ADJUSTMENT = "STOCK_ADJUSTMENT"
    REVERSAL = "REVERSAL"                # explicit correction of a prior txn


class Account(str, enum.Enum):
    """Which balance a ledger row affects. Kept separate from TxnType
    because e.g. a SALE_CASH row affects both CASH and STOCK."""
    CASH = "CASH"
    BANK = "BANK"
    STOCK = "STOCK"
    CUSTOMER_CREDIT = "CUSTOMER_CREDIT"
    SUPPLIER_PAYABLE = "SUPPLIER_PAYABLE"


class Direction(str, enum.Enum):
    IN = "IN"
    OUT = "OUT"


class PaymentMethod(str, enum.Enum):
    CASH = "CASH"
    BANK = "BANK"
    MIXED = "MIXED"
    CREDIT = "CREDIT"   # fully on credit, nothing received


class ActorType(str, enum.Enum):
    USER = "user"
    AI = "ai"
    IMPORT = "import"
    SYSTEM = "system"


class AuditAction(str, enum.Enum):
    CREATE = "CREATE"
    UPDATE = "UPDATE"
    DELETE = "DELETE"
    REVERSE = "REVERSE"
