"""
CreditService - owns `customers` (master data) and `credit_payments`.

Customer master data (create/list) lives here rather than in a
separate service because credit balance/payment logic is intrinsically
about a customer, and every write to Customer already needed to live
somewhere - see the top-level README for the full ownership map.

record_payment() handles a customer paying down existing credit
(business rule, project spec section 5, "Credit / Receivables"):
    Previous balance -> Payment -> Remaining balance = Previous - Payment
Remaining balance is never stored directly - it's always the Ledger
service's derivation, which already includes this payment once posted.

Same consistency model as SalesService (see its module docstring):
commit the local CreditPayment row FIRST (fast, no lock held across a
network call), then post to the Ledger service, and if that fails,
reverse whatever posted and delete the local row.
"""
import datetime as dt

from sqlalchemy.orm import Session

from common.core.enums import TxnType, Account, Direction, ActorType, PaymentMethod
from common.core.exceptions import ValidationError, NotFoundError
from common.ledger_client import LedgerClient
from common.models.business import CreditPayment
from common.models.master import Customer


class CreditService:
    def __init__(self, db: Session, ledger: LedgerClient | None = None):
        self.db = db
        self.ledger = ledger or LedgerClient()

    # ------------------------------------------------------------------
    # Customer master data
    # ------------------------------------------------------------------
    def create_customer(
        self,
        *,
        name: str,
        phone: str | None = None,
        disambiguator: str | None = None,
        opening_balance: float = 0,
        opening_balance_date: dt.date | None = None,
    ) -> Customer:
        customer = Customer(
            name=name,
            phone=phone,
            disambiguator=disambiguator,
            opening_balance=opening_balance,
            opening_balance_date=opening_balance_date,
        )
        self.db.add(customer)
        self.db.commit()
        self.db.refresh(customer)
        return customer

    def list_customers(self) -> list[Customer]:
        return self.db.query(Customer).filter(Customer.is_active.is_(True)).all()

    def get_customer(self, customer_id: int) -> Customer:
        customer = self.db.get(Customer, customer_id)
        if customer is None:
            raise NotFoundError(f"Customer {customer_id} does not exist")
        return customer

    # ------------------------------------------------------------------
    # Credit payments
    # ------------------------------------------------------------------
    def record_payment(
        self,
        *,
        payment_date: dt.date,
        customer_id: int,
        amount: float,
        payment_method: PaymentMethod = PaymentMethod.CASH,
        notes: str | None = None,
        allow_overpayment: bool = False,
        created_by: ActorType = ActorType.USER,
    ) -> CreditPayment:
        if amount <= 0:
            raise ValidationError("Payment amount must be > 0")
        if payment_method not in (PaymentMethod.CASH, PaymentMethod.BANK):
            raise ValidationError("Credit payments must be CASH or BANK, not MIXED/CREDIT")

        customer = self.db.get(Customer, customer_id)
        if customer is None:
            raise NotFoundError(f"Customer {customer_id} does not exist")

        previous_balance = self.ledger.get_customer_outstanding(customer_id)
        if not allow_overpayment and amount > previous_balance:
            raise ValidationError(
                f"Payment ({amount}) exceeds outstanding balance ({previous_balance}) for "
                f"{customer.name}. Pass allow_overpayment=True if this is intentional "
                f"(e.g. an advance payment)."
            )

        payment = CreditPayment(
            payment_date=payment_date,
            customer_id=customer_id,
            amount=amount,
            payment_method=payment_method,
            notes=notes,
            created_by=created_by,
        )
        self.db.add(payment)
        self.db.commit()
        self.db.refresh(payment)

        txn_dt = dt.datetime.combine(payment_date, dt.datetime.now().time())
        account = Account.CASH if payment_method == PaymentMethod.CASH else Account.BANK
        posted_txn_ids: list[int] = []

        try:
            row = self.ledger.post_transaction(
                txn_datetime=txn_dt,
                txn_type=TxnType.CREDIT_PAYMENT,
                account=account,
                direction=Direction.IN,
                amount=amount,
                customer_id=customer_id,
                reference_table="credit_payments",
                reference_id=payment.id,
                description=f"Credit payment received from {customer.name}",
                created_by=created_by,
            )
            posted_txn_ids.append(row["id"])

            row = self.ledger.post_transaction(
                txn_datetime=txn_dt,
                txn_type=TxnType.CREDIT_PAYMENT,
                account=Account.CUSTOMER_CREDIT,
                direction=Direction.OUT,
                amount=amount,
                customer_id=customer_id,
                reference_table="credit_payments",
                reference_id=payment.id,
                description=f"Credit reduced for {customer.name}",
                created_by=created_by,
            )
            posted_txn_ids.append(row["id"])
        except Exception:
            self.ledger.reverse_many(
                posted_txn_ids, reason=f"Compensating rollback: payment for {customer.name} failed mid-post"
            )
            self.db.delete(payment)
            self.db.commit()
            raise

        return payment

    def get_outstanding(self, customer_id: int, as_of: dt.date | None = None) -> float:
        return self.ledger.get_customer_outstanding(customer_id, as_of=as_of)

    def get_all_outstanding(self, as_of: dt.date | None = None) -> list[dict]:
        customers = self.db.query(Customer).filter(Customer.is_active.is_(True)).all()
        result = []
        for c in customers:
            balance = self.ledger.get_customer_outstanding(c.id, as_of=as_of)
            if balance != 0:
                result.append({"customer_id": c.id, "name": c.name, "outstanding": balance})
        return sorted(result, key=lambda r: -r["outstanding"])
