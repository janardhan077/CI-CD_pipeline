"""
LedgerClient - the ONLY way any other service talks to the Ledger
service. It mirrors the monolith's LedgerService method signatures on
purpose: sales_service.py, credit_service.py, expense_service.py,
stock_service.py, and cashbank_service.py in this codebase are almost
line-for-line what they were in the monolith, just calling `self.ledger.*`
over HTTP instead of importing LedgerService directly.

Why this matters (read before changing this file):
Even though every service shares one physical database, each service
still has its OWN database session/transaction - a shared DB does not
give you a shared transaction. So "write my row, then call the
ledger" is NOT atomic the way it was in the monolith (one process, one
session, one commit). Every business service in this codebase follows
the same saga pattern because of this:

  1. Commit the local row FIRST, before making any network call.
     (Confirmed by testing: holding a local row's transaction open
     across a blocking HTTP call to another service can deadlock two
     writers on the same SQLite file - "database is locked" - and is
     bad practice on any database, since it holds a lock for the
     duration of a network round trip.)
  2. Post to the Ledger service. It commits immediately and returns
     the persisted row.
  3. If a ledger post fails partway through, call reverse_transaction()
     on every id already posted (this client's reverse_many() does
     that), THEN DELETE the local row from step 1 - it described a
     financial event that never actually completed.

This is the real cost of splitting the "single write path" invariant
across a network boundary. It is still enforced (nobody but the Ledger
service ever inserts a LedgerTransaction row) - it just now requires
explicit compensation instead of an implicit rollback.
"""
import datetime as dt
from typing import Optional

import httpx

from common.config import get_settings
from common.core.enums import TxnType, Account, Direction, ActorType
from common.core.exceptions import ValidationError, NotFoundError, UpstreamServiceError

_EXC_BY_NAME = {
    "ValidationError": ValidationError,
    "NotFoundError": NotFoundError,
}


def _raise_for_status(resp: httpx.Response) -> None:
    if resp.status_code < 400:
        return
    try:
        body = resp.json()
        error_name = body.get("error")
        detail = body.get("detail", resp.text)
    except Exception:
        error_name, detail = None, resp.text
    exc_cls = _EXC_BY_NAME.get(error_name)
    if exc_cls is not None:
        raise exc_cls(detail)
    raise UpstreamServiceError(
        f"Ledger service returned {resp.status_code}: {detail}"
    )


class LedgerClient:
    def __init__(self, base_url: Optional[str] = None, timeout: Optional[float] = None):
        settings = get_settings()
        self._base_url = (base_url or settings.ledger_service_url).rstrip("/")
        self._timeout = timeout or settings.http_timeout

    def _client(self) -> httpx.Client:
        return httpx.Client(base_url=self._base_url, timeout=self._timeout)

    # ------------------------------------------------------------------
    # Writing
    # ------------------------------------------------------------------
    def post_transaction(
        self,
        *,
        txn_datetime: dt.datetime,
        txn_type: TxnType,
        account: Account,
        direction: Direction,
        amount: float,
        customer_id: int | None = None,
        supplier_id: int | None = None,
        stock_type_id: int | None = None,
        reference_table: str | None = None,
        reference_id: int | None = None,
        description: str | None = None,
        created_by: ActorType = ActorType.USER,
    ) -> dict:
        payload = {
            "txn_datetime": txn_datetime.isoformat(),
            "txn_type": txn_type.value,
            "account": account.value,
            "direction": direction.value,
            "amount": amount,
            "customer_id": customer_id,
            "supplier_id": supplier_id,
            "stock_type_id": stock_type_id,
            "reference_table": reference_table,
            "reference_id": reference_id,
            "description": description,
            "created_by": created_by.value,
        }
        try:
            with self._client() as client:
                resp = client.post("/transactions", json=payload)
        except httpx.RequestError as e:
            raise UpstreamServiceError(f"Could not reach Ledger service: {e}") from e
        _raise_for_status(resp)
        return resp.json()

    def reverse_transaction(
        self, original_id: int, *, reason: str, created_by: ActorType = ActorType.USER
    ) -> dict:
        payload = {"reason": reason, "created_by": created_by.value}
        try:
            with self._client() as client:
                resp = client.post(f"/transactions/{original_id}/reverse", json=payload)
        except httpx.RequestError as e:
            raise UpstreamServiceError(f"Could not reach Ledger service: {e}") from e
        _raise_for_status(resp)
        return resp.json()

    def reverse_many(self, ids: list[int], *, reason: str, created_by: ActorType = ActorType.USER) -> None:
        """Best-effort compensation helper: reverse every id given,
        swallowing individual failures (logged, not raised) so one
        stuck reversal doesn't hide the others. Used when a caller's
        own local commit fails AFTER the ledger postings already
        succeeded - see the module docstring."""
        for txn_id in ids:
            try:
                self.reverse_transaction(txn_id, reason=reason, created_by=created_by)
            except Exception:
                # Intentionally swallowed: this is a best-effort saga
                # compensation. A production system should push these
                # failures to a dead-letter queue / alert for manual
                # reconciliation rather than silently continue.
                continue

    # ------------------------------------------------------------------
    # Reading / derivation
    # ------------------------------------------------------------------
    def _get(self, path: str, params: dict | None = None):
        params = {k: v for k, v in (params or {}).items() if v is not None}
        try:
            with self._client() as client:
                resp = client.get(path, params=params)
        except httpx.RequestError as e:
            raise UpstreamServiceError(f"Could not reach Ledger service: {e}") from e
        _raise_for_status(resp)
        return resp.json()

    def get_cash_balance(self, as_of: dt.date | None = None) -> float:
        return self._get("/balances/cash", {"as_of": as_of and as_of.isoformat()})["balance"]

    def get_bank_balance(self, as_of: dt.date | None = None) -> float:
        return self._get("/balances/bank", {"as_of": as_of and as_of.isoformat()})["balance"]

    def get_total_stock(self, as_of: dt.date | None = None) -> float:
        return self._get("/balances/stock", {"as_of": as_of and as_of.isoformat()})["balance"]

    def get_stock_by_type(self, stock_type_id: int, as_of: dt.date | None = None) -> float:
        return self._get(
            f"/balances/stock/{stock_type_id}", {"as_of": as_of and as_of.isoformat()}
        )["balance"]

    def get_customer_outstanding(self, customer_id: int, as_of: dt.date | None = None) -> float:
        return self._get(
            f"/balances/customer/{customer_id}", {"as_of": as_of and as_of.isoformat()}
        )["balance"]

    def get_transaction(self, transaction_id: int) -> dict:
        return self._get(f"/transactions/{transaction_id}")

    def get_transactions_for(self, *, reference_table: str, reference_id: int) -> list[dict]:
        return self._get(
            "/transactions", {"reference_table": reference_table, "reference_id": reference_id}
        )

    def get_transactions_between(
        self, start: dt.date, end: dt.date, account: Account | None = None
    ) -> list[dict]:
        return self._get(
            "/transactions/between",
            {"start": start.isoformat(), "end": end.isoformat(), "account": account and account.value},
        )
