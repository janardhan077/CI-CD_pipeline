"""
Peer-service HTTP clients for the Assistant service.

The Assistant service holds NO database connection at all, to anyone's
database - not even its own. Every read and every write it performs
goes through another service's normal REST API, the exact same API a
human using the UI hits. This is a stronger version of the monolith's
"the AI should not directly access the database" rule: there, the AI
called the same Python service *classes* the API used; here, it's
forced to go over the network through the same *endpoints*, so there
is no code path left that could let it touch a table directly even by
accident.
"""
import datetime as dt

import httpx

from common.config import get_settings
from common.core.exceptions import ValidationError, NotFoundError, InsufficientStockError, UpstreamServiceError

_EXC_BY_NAME = {
    "ValidationError": ValidationError,
    "NotFoundError": NotFoundError,
    "InsufficientStockError": InsufficientStockError,
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
    raise UpstreamServiceError(f"{resp.request.url} returned {resp.status_code}: {detail}")


def _call(method: str, base_url: str, path: str, **kwargs) -> httpx.Response:
    timeout = get_settings().http_timeout
    try:
        with httpx.Client(base_url=base_url, timeout=timeout) as client:
            resp = client.request(method, path, **kwargs)
    except httpx.RequestError as e:
        raise UpstreamServiceError(f"Could not reach {base_url}: {e}") from e
    _raise_for_status(resp)
    return resp


# ---------------------------------------------------------------------
# Master data lookups (used to resolve names -> ids, never ids -> the
# AI itself never sees or handles a database id).
# ---------------------------------------------------------------------
def list_customers() -> list[dict]:
    return _call("GET", get_settings().credit_service_url, "/customers").json()


def list_stock_types() -> list[dict]:
    return _call("GET", get_settings().stock_service_url, "/stock/types").json()


def list_expense_categories() -> list[dict]:
    return _call("GET", get_settings().expense_service_url, "/expenses/categories").json()


# ---------------------------------------------------------------------
# Writes - each hits the exact same endpoint the UI's forms hit.
# ---------------------------------------------------------------------
def create_sale(**payload) -> dict:
    return _call("POST", get_settings().sales_service_url, "/sales", json=_jsonable(payload)).json()


def create_expense(**payload) -> dict:
    return _call("POST", get_settings().expense_service_url, "/expenses", json=_jsonable(payload)).json()


def create_credit_payment(customer_id: int, **payload) -> dict:
    return _call(
        "POST", get_settings().credit_service_url, f"/customers/{customer_id}/payments", json=_jsonable(payload)
    ).json()


def create_purchase(**payload) -> dict:
    return _call("POST", get_settings().stock_service_url, "/stock/purchases", json=_jsonable(payload)).json()


def create_stock_adjustment(**payload) -> dict:
    return _call("POST", get_settings().stock_service_url, "/stock/adjustments", json=_jsonable(payload)).json()


# ---------------------------------------------------------------------
# Reads used to answer questions.
# ---------------------------------------------------------------------
def get_stock_snapshot() -> list[dict]:
    return _call("GET", get_settings().stock_service_url, "/stock/snapshot").json()


def get_customer_balance(customer_id: int) -> dict:
    return _call("GET", get_settings().credit_service_url, f"/customers/{customer_id}/balance").json()


def get_all_customer_outstanding() -> list[dict]:
    return _call("GET", get_settings().credit_service_url, "/customers/credit/outstanding").json()


def get_sales_for_date(sale_date: dt.date) -> list[dict]:
    return _call(
        "GET", get_settings().sales_service_url, "/sales", params={"sale_date": sale_date.isoformat()}
    ).json()


def get_expense_total(start: dt.date, end: dt.date) -> float:
    return _call(
        "GET", get_settings().expense_service_url, "/expenses/total",
        params={"start": start.isoformat(), "end": end.isoformat()},
    ).json()["total"]


def get_daily_report_text(report_date: dt.date) -> str:
    resp = _call(
        "GET", get_settings().report_service_url, "/reports/daily/text",
        params={"report_date": report_date.isoformat()},
    )
    return resp.text


def get_expenses(expense_date: dt.date | None = None, category_id: int | None = None) -> list[dict]:
    params = {}
    if expense_date is not None:
        params["expense_date"] = expense_date.isoformat()
    if category_id is not None:
        params["category_id"] = category_id
    return _call("GET", get_settings().expense_service_url, "/expenses", params=params).json()


def correct_expense(expense_id: int, **payload) -> dict:
    return _call(
        "POST", get_settings().expense_service_url, f"/expenses/{expense_id}/correct", json=_jsonable(payload)
    ).json()


def get_recent_business_summary(days: int = 7) -> str:
    """Grounds general_query predictions/estimates in real numbers
    instead of letting the model invent them. Deliberately simple -
    a handful of extra HTTP calls to services that already exist,
    nothing new to maintain, and it's only used for a caveated
    estimate, never a number that gets written anywhere."""
    today = dt.date.today()
    lines = []

    try:
        snapshot = get_stock_snapshot()
        lines.append("Current stock: " + "; ".join(f"{s['name']}: {s['quantity']} {s['unit']}(s)" for s in snapshot))
    except Exception:
        pass

    try:
        outstanding = get_all_customer_outstanding()
        total_credit = sum(o["outstanding"] for o in outstanding)
        lines.append(f"Total outstanding customer credit: \u20b9{total_credit:,.2f}")
    except Exception:
        pass

    total_sales, total_bags, total_expenses = 0.0, 0.0, 0.0
    daily_sales = []
    for i in range(days):
        d = today - dt.timedelta(days=i)
        try:
            sales = get_sales_for_date(d)
            day_total = sum(float(s["total_amount"]) for s in sales)
            total_sales += day_total
            total_bags += sum(float(s["quantity"]) for s in sales)
            daily_sales.append(day_total)
        except Exception:
            pass
    try:
        total_expenses = get_expense_total(today - dt.timedelta(days=days - 1), today)
    except Exception:
        pass

    if daily_sales:
        avg_daily_sales = total_sales / days
        lines.append(
            f"Last {days} days: total sales \u20b9{total_sales:,.2f} ({total_bags:g} bags), "
            f"average \u20b9{avg_daily_sales:,.2f}/day; total expenses \u20b9{total_expenses:,.2f} "
            f"over the same period."
        )
    return "\n".join(lines)


def _jsonable(payload: dict) -> dict:
    """dt.date -> ISO string; None values pass through so FastAPI/Pydantic
    on the other end applies its own defaults."""
    out = {}
    for k, v in payload.items():
        if isinstance(v, (dt.date, dt.datetime)):
            out[k] = v.isoformat()
        else:
            out[k] = v
    return out
