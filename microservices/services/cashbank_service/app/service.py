"""
CashBankService - owns NO table of its own.

Handles manual cash/bank adjustments not tied to a sale, expense, or
purchase (e.g. the owner deposits personal cash, or transfers cash to
the bank). A transfer is modeled as a paired CASH_OUT + BANK_IN (or
vice versa) so it never appears in totals as new money - it's a
category swap between the two accounts.

Because this service has no local table, there is no "commit last"
step and no compensation to worry about for single-call operations
(adjust_cash/adjust_bank) - the Ledger service's own commit is the only
commit involved. `transfer_cash_to_bank` posts two ledger rows; if the
second fails after the first succeeds, it reverses the first so a
transfer never leaves half-applied.
"""
import datetime as dt

from common.core.enums import TxnType, Account, Direction, ActorType
from common.core.exceptions import ValidationError
from common.ledger_client import LedgerClient


class CashBankService:
    def __init__(self, ledger: LedgerClient | None = None):
        self.ledger = ledger or LedgerClient()

    def adjust_cash(
        self, *, date: dt.date, amount: float, direction: Direction, reason: str,
        created_by: ActorType = ActorType.USER,
    ) -> dict:
        if amount <= 0:
            raise ValidationError("Adjustment amount must be > 0")
        txn_type = TxnType.CASH_IN if direction == Direction.IN else TxnType.CASH_OUT
        return self.ledger.post_transaction(
            txn_datetime=dt.datetime.combine(date, dt.datetime.now().time()),
            txn_type=txn_type,
            account=Account.CASH,
            direction=direction,
            amount=amount,
            description=reason,
            created_by=created_by,
        )

    def adjust_bank(
        self, *, date: dt.date, amount: float, direction: Direction, reason: str,
        created_by: ActorType = ActorType.USER,
    ) -> dict:
        if amount <= 0:
            raise ValidationError("Adjustment amount must be > 0")
        txn_type = TxnType.BANK_IN if direction == Direction.IN else TxnType.BANK_OUT
        return self.ledger.post_transaction(
            txn_datetime=dt.datetime.combine(date, dt.datetime.now().time()),
            txn_type=txn_type,
            account=Account.BANK,
            direction=direction,
            amount=amount,
            description=reason,
            created_by=created_by,
        )

    def transfer_cash_to_bank(
        self, *, date: dt.date, amount: float, reason: str = "Cash deposited to bank",
        created_by: ActorType = ActorType.USER,
    ) -> tuple[dict, dict]:
        if amount <= 0:
            raise ValidationError("Transfer amount must be > 0")
        txn_dt = dt.datetime.combine(date, dt.datetime.now().time())
        cash_out = self.ledger.post_transaction(
            txn_datetime=txn_dt, txn_type=TxnType.CASH_OUT, account=Account.CASH,
            direction=Direction.OUT, amount=amount, description=reason, created_by=created_by,
        )
        try:
            bank_in = self.ledger.post_transaction(
                txn_datetime=txn_dt, txn_type=TxnType.BANK_IN, account=Account.BANK,
                direction=Direction.IN, amount=amount, description=reason, created_by=created_by,
            )
        except Exception:
            # First leg succeeded, second failed - don't leave cash
            # looking like it vanished. Reverse the cash-out leg.
            self.ledger.reverse_many(
                [cash_out["id"]], reason="Compensating rollback: transfer-to-bank failed on bank leg"
            )
            raise
        return cash_out, bank_in

    def get_balances(self, as_of: dt.date | None = None) -> dict:
        return {
            "cash": self.ledger.get_cash_balance(as_of=as_of),
            "bank": self.ledger.get_bank_balance(as_of=as_of),
        }
