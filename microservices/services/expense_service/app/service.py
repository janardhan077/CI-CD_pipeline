"""
ExpenseService - owns `expenses` and `expense_categories`.

An expense always reduces exactly one account (CASH or BANK) - it
never touches stock or customer credit. Same consistency model as the
other business services (see sales_service.py's module docstring):
commit the local Expense row first, then post to the Ledger, and
delete the local row if the ledger post fails.
"""
import datetime as dt

from sqlalchemy.orm import Session

from common.core.enums import TxnType, Account, Direction, ActorType, PaymentMethod
from common.core.exceptions import ValidationError, NotFoundError
from common.ledger_client import LedgerClient
from common.models.business import Expense
from common.models.master import ExpenseCategory


class ExpenseService:
    def __init__(self, db: Session, ledger: LedgerClient | None = None):
        self.db = db
        self.ledger = ledger or LedgerClient()

    # ------------------------------------------------------------------
    # Categories (master data)
    # ------------------------------------------------------------------
    def create_category(self, *, name: str) -> ExpenseCategory:
        category = ExpenseCategory(name=name)
        self.db.add(category)
        self.db.commit()
        self.db.refresh(category)
        return category

    def list_categories(self) -> list[ExpenseCategory]:
        return self.db.query(ExpenseCategory).filter(ExpenseCategory.is_active.is_(True)).all()

    # ------------------------------------------------------------------
    # Expenses
    # ------------------------------------------------------------------
    def record_expense(
        self,
        *,
        expense_date: dt.date,
        category_id: int,
        amount: float,
        payment_method: PaymentMethod = PaymentMethod.CASH,
        description: str | None = None,
        notes: str | None = None,
        created_by: ActorType = ActorType.USER,
    ) -> Expense:
        if amount <= 0:
            raise ValidationError("Expense amount must be > 0")
        if payment_method not in (PaymentMethod.CASH, PaymentMethod.BANK):
            raise ValidationError("Expenses must be paid CASH or BANK")

        category = self.db.get(ExpenseCategory, category_id)
        if category is None:
            raise NotFoundError(f"ExpenseCategory {category_id} does not exist")

        expense = Expense(
            expense_date=expense_date,
            category_id=category_id,
            amount=amount,
            payment_method=payment_method,
            description=description,
            notes=notes,
            created_by=created_by,
        )
        self.db.add(expense)
        self.db.commit()
        self.db.refresh(expense)

        txn_dt = dt.datetime.combine(expense_date, dt.datetime.now().time())
        account = Account.CASH if payment_method == PaymentMethod.CASH else Account.BANK

        try:
            self.ledger.post_transaction(
                txn_datetime=txn_dt,
                txn_type=TxnType.EXPENSE,
                account=account,
                direction=Direction.OUT,
                amount=amount,
                reference_table="expenses",
                reference_id=expense.id,
                description=description or f"{category.name} expense",
                created_by=created_by,
            )
        except Exception:
            self.db.delete(expense)
            self.db.commit()
            raise

        return expense

    def list_expenses(
        self, *, expense_date: dt.date | None = None, category_id: int | None = None
    ) -> list[Expense]:
        """Read-only listing, used by the Assistant service to find a
        previously-recorded expense the owner wants corrected
        ("update_expense" intent) - it never guesses which row to
        touch, it looks the candidates up here first. Voided rows
        (already superseded by a correction) are excluded."""
        query = self.db.query(Expense).filter(Expense.voided_at.is_(None))
        if expense_date is not None:
            query = query.filter(Expense.expense_date == expense_date)
        if category_id is not None:
            query = query.filter(Expense.category_id == category_id)
        return query.order_by(Expense.expense_date, Expense.id).all()

    def get_expense(self, expense_id: int) -> Expense:
        expense = self.db.get(Expense, expense_id)
        if expense is None:
            raise NotFoundError(f"Expense {expense_id} does not exist")
        return expense

    def correct_expense(
        self,
        expense_id: int,
        *,
        new_amount: float | None = None,
        new_category_id: int | None = None,
        new_payment_method: PaymentMethod | None = None,
        new_description: str | None = None,
        reason: str = "Corrected via assistant",
        created_by: ActorType = ActorType.USER,
    ) -> tuple[Expense, Expense]:
        """Never edits a row in place. Voids the original expense,
        reverses its ledger transaction, and records a brand-new
        corrected expense - so the audit trail always shows both what
        was originally entered and what it was changed to, and the
        ledger's append-only guarantee is never broken.

        Dating note: the reversal is timestamped at correction time
        (now), not backdated to the original expense's date - the same
        rule real bookkeeping follows for a correcting entry, and the
        same thing the Ledger service does for every reversal (see
        LedgerService.reverse_transaction). Practically: a daily report
        for the ORIGINAL date still shows that day's records exactly as
        they were entered that day; the correction's net effect shows
        up on the day the correction was actually made. Correcting a
        same-day expense (the common case, e.g. via the assistant) nets
        out within that same day's report as expected.

        Returns (old_expense, new_expense).
        """
        old = self.get_expense(expense_id)
        if old.voided_at is not None:
            raise ValidationError(
                f"Expense {expense_id} was already corrected/voided - it can't be corrected again. "
                f"Correct the newer entry instead."
            )

        amount = new_amount if new_amount is not None else float(old.amount)
        category_id = new_category_id if new_category_id is not None else old.category_id
        payment_method = new_payment_method if new_payment_method is not None else old.payment_method
        description = new_description if new_description is not None else old.description

        if amount <= 0:
            raise ValidationError("Corrected expense amount must be > 0")
        category = self.db.get(ExpenseCategory, category_id)
        if category is None:
            raise NotFoundError(f"ExpenseCategory {category_id} does not exist")

        # Step 1: void the old row FIRST (fast local commit, no network
        # call yet) - same "commit before calling out" rule as every
        # other write in this codebase, see ledger_client.py.
        old.voided_at = dt.datetime.now(dt.timezone.utc)
        old.voided_reason = reason
        self.db.commit()

        # Step 2: reverse the old row's ledger effect.
        old_txns = self.ledger.get_transactions_for(reference_table="expenses", reference_id=old.id)
        reversal_ids: list[int] = []
        try:
            for txn in old_txns:
                reversal = self.ledger.reverse_transaction(
                    txn["id"], reason=f"Correcting expense #{old.id}: {reason}", created_by=created_by
                )
                reversal_ids.append(reversal["id"])
        except Exception:
            # Couldn't reverse the old ledger effect - undo the void so
            # the original expense is still the active, correct record.
            old.voided_at = None
            old.voided_reason = None
            self.db.commit()
            raise

        # Step 3: record the corrected expense as a normal new expense.
        try:
            new_expense = self.record_expense(
                expense_date=old.expense_date,
                category_id=category_id,
                amount=amount,
                payment_method=payment_method,
                description=description,
                notes=f"Correction of expense #{old.id} ({reason})",
                created_by=created_by,
            )
        except Exception:
            # Couldn't record the corrected expense - put the original
            # back exactly as it was: re-reverse each reversal (which
            # restores the original ledger effect) and un-void the row.
            for rid in reversal_ids:
                try:
                    self.ledger.reverse_transaction(
                        rid, reason=f"Restoring expense #{old.id} after failed correction", created_by=created_by
                    )
                except Exception:
                    continue  # best-effort - see reverse_many()'s docstring for why
            old.voided_at = None
            old.voided_reason = None
            self.db.commit()
            raise

        return old, new_expense

    def total_between(self, start: dt.date, end: dt.date) -> float:
        # Filter by reference_table, not txn_type=="EXPENSE": a
        # correction (correct_expense) reverses the original posting,
        # and that reversal row's txn_type is "REVERSAL", not
        # "EXPENSE" - filtering on txn_type alone would count the
        # original spend but miss the reversal that cancels part of
        # it, silently double-counting corrected expenses. Net
        # OUT-minus-IN on this reference_table is the actual money
        # spent on expenses in the period, matching how the Ledger
        # service derives every other balance.
        txns = self.ledger.get_transactions_between(start, end)
        total = 0.0
        for t in txns:
            if t.get("reference_table") != "expenses":
                continue
            if t["direction"] == Direction.OUT.value:
                total += float(t["amount"])
            elif t["direction"] == Direction.IN.value:
                total -= float(t["amount"])
        return total

    def breakdown_between(self, start: dt.date, end: dt.date) -> list[dict]:
        expenses = (
            self.db.query(Expense)
            .filter(Expense.expense_date >= start, Expense.expense_date <= end, Expense.voided_at.is_(None))
            .all()
        )
        totals: dict[str, float] = {}
        for e in expenses:
            cat_name = e.category.name if e.category else "Uncategorized"
            totals[cat_name] = totals.get(cat_name, 0) + float(e.amount)
        return [{"category": k, "amount": v} for k, v in sorted(totals.items(), key=lambda kv: -kv[1])]
