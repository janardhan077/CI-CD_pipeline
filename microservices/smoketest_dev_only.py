import importlib
import os
import sys
import datetime as dt

import httpx
from starlette.testclient import TestClient

ROOT = "/home/claude/work/microservices"
DB_PATH = "/home/claude/work/microservices/data/smoketest.db"
for p in (DB_PATH, DB_PATH + "-wal", DB_PATH + "-shm"):
    if os.path.exists(p):
        os.remove(p)
os.environ["INON_DATABASE_URL"] = f"sqlite:///{DB_PATH}"
sys.path.insert(0, ROOT)


def load_service_app(service_dir: str):
    for mod_name in list(sys.modules):
        if mod_name == "app" or mod_name.startswith("app."):
            del sys.modules[mod_name]
    service_path = os.path.join(ROOT, "services", service_dir)
    sys.path = [p for p in sys.path if not p.startswith(os.path.join(ROOT, "services"))]
    sys.path.insert(0, service_path)
    return importlib.import_module("app.main").app


ledger_app = load_service_app("ledger_service")
import common.ledger_client as lc  # noqa: E402

_ledger_test_client = TestClient(ledger_app, base_url="http://ledger").__enter__()


class _NonClosingWrapper:
    def __init__(self, inner): self._inner = inner
    def __enter__(self): return self._inner
    def __exit__(self, *exc): return False


lc.LedgerClient._client = lambda self: _NonClosingWrapper(_ledger_test_client)

results = {"pass": 0, "fail": 0}


def check(label, cond, extra=""):
    status = "PASS" if cond else "FAIL"
    results["pass" if cond else "fail"] += 1
    print(f"[{status}] {label} {extra}")


def make_test_client(service_dir):
    app = load_service_app(service_dir)
    return TestClient(app, base_url=f"http://{service_dir}").__enter__()


credit_client = make_test_client("credit_service")
stock_client = make_test_client("stock_service")
cashbank_client = make_test_client("cashbank_service")
sales_client = make_test_client("sales_service")
expense_client = make_test_client("expense_service")

r = credit_client.post("/customers", json={"name": "Ramesh Traders"})
check("create customer", r.status_code == 201, r.text)
customer_id = r.json()["id"]

r = stock_client.post("/stock/types", json={"name": "Mayur", "unit": "bag"})
check("create stock type", r.status_code == 201, r.text)
stock_type_id = r.json()["id"]

r = stock_client.post("/stock/purchases", json={
    "purchase_date": "2026-08-01", "stock_type_id": stock_type_id, "quantity": 500, "rate": 500,
})
check("record purchase", r.status_code == 201, r.text)

r = cashbank_client.post("/cashbank/cash/in", json={"date": "2026-08-01", "amount": 300000, "reason": "capital"})
check("cash-in", r.status_code == 201, r.text)

r = sales_client.post("/sales", json={
    "sale_date": "2026-08-02", "customer_id": customer_id, "stock_type_id": stock_type_id,
    "quantity": 20, "rate": 600, "cash_received": 8000,
})
check("record sale", r.status_code == 201, r.text)

r = stock_client.get("/stock/snapshot")
check("stock is 480 after sale", r.json()[0]["quantity"] == 480.0, r.text)

# Simulate "used 400 bags of Mayur today" -> a negative stock adjustment,
# exactly the scenario requested: chatbot-style write, verified end to end.
r = stock_client.post("/stock/adjustments", json={
    "adjustment_date": "2026-08-02", "stock_type_id": stock_type_id,
    "quantity_delta": -400, "reason": "used",
})
check("negative stock adjustment accepted", r.status_code == 201, r.text)

r = stock_client.get("/stock/snapshot")
check("stock is 80 after 'used 400' adjustment", r.json()[0]["quantity"] == 80.0, r.text)

# Ledger trace-back: the adjustment must be visible as a real ledger row.
r = _ledger_test_client.get("/transactions", params={"reference_table": "stock_adjustments", "reference_id": 1})
check("adjustment traceable in ledger", r.status_code == 200 and len(r.json()) == 1 and r.json()[0]["amount"] == 400.0, r.text)

print(f"\n{results['pass']} passed, {results['fail']} failed")
sys.exit(1 if results["fail"] else 0)
