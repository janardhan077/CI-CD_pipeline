"""
Read-only HTTP clients for the Report service.

The Report service owns no table of its own - it is a pure aggregator
over the other services' read APIs, the same way `common.ledger_client`
is the one path to the Ledger service. Kept separate from
common/ledger_client.py because these are simple GET-only calls with
no write/compensation logic to share.
"""
import datetime as dt

import httpx

from common.config import get_settings
from common.core.exceptions import UpstreamServiceError


def _get(base_url: str, path: str, params: dict | None = None):
    params = {k: v for k, v in (params or {}).items() if v is not None}
    try:
        with httpx.Client(base_url=base_url, timeout=get_settings().http_timeout) as client:
            resp = client.get(path, params=params)
    except httpx.RequestError as e:
        raise UpstreamServiceError(f"Could not reach {base_url}: {e}") from e
    if resp.status_code >= 400:
        raise UpstreamServiceError(f"{base_url}{path} returned {resp.status_code}: {resp.text}")
    return resp.json()


def get_sales_for_date(sale_date: dt.date) -> list[dict]:
    settings = get_settings()
    return _get(settings.sales_service_url, "/sales", {"sale_date": sale_date.isoformat()})


def get_expense_total(start: dt.date, end: dt.date) -> float:
    settings = get_settings()
    return _get(settings.expense_service_url, "/expenses/total", {"start": start.isoformat(), "end": end.isoformat()})["total"]


def get_expense_breakdown(start: dt.date, end: dt.date) -> list[dict]:
    settings = get_settings()
    return _get(settings.expense_service_url, "/expenses/breakdown", {"start": start.isoformat(), "end": end.isoformat()})


def get_stock_snapshot(as_of: dt.date | None = None) -> list[dict]:
    settings = get_settings()
    return _get(settings.stock_service_url, "/stock/snapshot", {"as_of": as_of and as_of.isoformat()})


def get_all_customer_outstanding(as_of: dt.date | None = None) -> list[dict]:
    settings = get_settings()
    return _get(settings.credit_service_url, "/customers/credit/outstanding", {"as_of": as_of and as_of.isoformat()})
