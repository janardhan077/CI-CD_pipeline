import importlib
import os
import sys
import datetime as dt

import httpx
from starlette.testclient import TestClient

ROOT = "/home/claude/work/microservices"
DB_PATH = "/home/claude/work/microservices/data/smoketest2.db"
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

_test_clients = {}


def make_test_client(service_dir):
    app = load_service_app(service_dir)
    client = TestClient(app, base_url=f"http://{service_dir}").__enter__()
    _test_clients[service_dir] = client
    return client


_URL_TO_SERVICE_DIR = {}


def _install_httpx_client_patch():
    real_client_cls = httpx.Client

    class RoutingClient:
        def __init__(self, *a, base_url="", timeout=None, **kw):
            self._base_url = str(base_url)

        def __enter__(self):
            sd = _URL_TO_SERVICE_DIR.get(self._base_url)
            if sd is None:
                self._real = real_client_cls(base_url=self._base_url)
                return self._real
            return _test_clients[sd]

        def __exit__(self, *exc):
            return False

    httpx.Client = RoutingClient


results = {"pass": 0, "fail": 0}


def check(label, cond, extra=""):
    status = "PASS" if cond else "FAIL"
    results["pass" if cond else "fail"] += 1
    print(f"[{status}] {label} {extra}")


credit_client = make_test_client("credit_service")
stock_client = make_test_client("stock_service")
cashbank_client = make_test_client("cashbank_service")
sales_client = make_test_client("sales_service")
expense_client = make_test_client("expense_service")

r = credit_client.post("/customers", json={"name": "Ramesh Traders"})
customer_id = r.json()["id"]
r = stock_client.post("/stock/types", json={"name": "Mayur", "unit": "bag"})
stock_type_id = r.json()["id"]
r = stock_client.post("/stock/purchases", json={
    "purchase_date": "2026-08-01", "stock_type_id": stock_type_id, "quantity": 500, "rate": 500,
})
check("setup: purchase", r.status_code == 201, r.text)
r = cashbank_client.post("/cashbank/cash/in", json={"date": "2026-08-01", "amount": 300000, "reason": "capital"})
check("setup: capital", r.status_code == 201, r.text)

_URL_TO_SERVICE_DIR["http://sales-service:8000"] = "sales_service"
_URL_TO_SERVICE_DIR["http://credit-service:8000"] = "credit_service"
_URL_TO_SERVICE_DIR["http://expense-service:8000"] = "expense_service"
_URL_TO_SERVICE_DIR["http://stock-service:8000"] = "stock_service"
_URL_TO_SERVICE_DIR["http://cashbank-service:8000"] = "cashbank_service"
_install_httpx_client_patch()

report_client = make_test_client("report_service")
_URL_TO_SERVICE_DIR["http://report-service:8000"] = "report_service"

assistant_app = load_service_app("assistant_service")
from app.schemas import Intent, IntentAction  # noqa: E402
import app.ollama_client as assistant_ollama  # noqa: E402
import app.main as assistant_main  # noqa: E402

_next_intent = {}


class FakeOllamaClient:
    def extract_intent(self, message, timeout=60.0):
        return _next_intent["value"]


assistant_main.OllamaClient = FakeOllamaClient
assistant_client = TestClient(assistant_app, base_url="http://assistant_service").__enter__()
_test_clients["assistant_service"] = assistant_client
_URL_TO_SERVICE_DIR["http://assistant-service:8000"] = "assistant_service"

# ----------------------------------------------------------------------
# THE requested scenario: "the stock used for today is 400 something"
# should hit the real database through the assistant, with the correct
# sign (stock decreases), and be immediately reflected in stock/report.
# ----------------------------------------------------------------------
_next_intent["value"] = Intent(
    action=IntentAction.RECORD_STOCK_ADJUSTMENT,
    stock_type_name="mayur", quantity=-400, reason="used", date=dt.date(2026, 8, 2),
)
r = assistant_client.post("/assistant/chat", json={"message": "stock used for today is 400 bags of mayur"})
body = r.json()
check("assistant records negative stock usage", r.status_code == 200 and body["status"] == "ok", body)
check("response reports affected=['stock']", body.get("data", {}).get("affected") == ["stock"], body)

r = stock_client.get("/stock/snapshot")
check("actual stock table now 100 (500-400)", r.json()[0]["quantity"] == 100.0, r.text)

r = report_client.get("/reports/daily", params={"report_date": "2026-08-02"})
check("'the sheet' (daily report) reflects it too", r.json()["closing_stock"] == 100.0, r.json())

# A second identical-looking case but phrased as an increase - sign flip works.
_next_intent["value"] = Intent(
    action=IntentAction.RECORD_STOCK_ADJUSTMENT,
    stock_type_name="mayur", quantity=15, reason="recount - found extra", date=dt.date(2026, 8, 2),
)
r = assistant_client.post("/assistant/chat", json={"message": "recounted mayur, found 15 extra bags"})
check("assistant records positive stock correction", r.json()["status"] == "ok", r.json())
r = stock_client.get("/stock/snapshot")
check("stock now 115 after +15 correction", r.json()[0]["quantity"] == 115.0, r.text)

print(f"\n{results['pass']} passed, {results['fail']} failed")
sys.exit(1 if results["fail"] else 0)
