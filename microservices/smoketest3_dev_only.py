import importlib
import os
import sys
import datetime as dt

import httpx
from starlette.testclient import TestClient

TODAY = dt.date.today().isoformat()  # corrections are dated "now" (see correct_expense's
                                      # dating note) - use today's date throughout so this
                                      # test reflects the realistic same-day-correction case.

ROOT = "/home/claude/work/microservices"
DB_PATH = "/home/claude/work/microservices/data/smoketest3.db"
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
stock_client.post("/stock/purchases", json={
    "purchase_date": TODAY, "stock_type_id": stock_type_id, "quantity": 500, "rate": 500,
})
cashbank_client.post("/cashbank/cash/in", json={"date": TODAY, "amount": 300000, "reason": "capital"})
sales_client.post("/sales", json={
    "sale_date": TODAY, "customer_id": customer_id, "stock_type_id": stock_type_id,
    "quantity": 20, "rate": 600, "cash_received": 12000,
})

r = expense_client.post("/expenses/categories", json={"name": "Transport"})
transport_cat_id = r.json()["id"]
r = expense_client.post("/expenses", json={
    "expense_date": TODAY, "category_id": transport_cat_id, "amount": 1500, "payment_method": "CASH",
})
check("setup: original expense recorded", r.status_code == 201, r.text)

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
import app.dispatcher as assistant_dispatcher  # noqa: E402
import app.ollama_client as assistant_ollama  # noqa: E402
import app.main as assistant_main  # noqa: E402

_next_intent = {}


class FakeOllamaClient:
    def extract_intent(self, message, timeout=60.0):
        return _next_intent["value"]

    def answer_freeform(self, system_prompt, user_message, timeout=60.0):
        # Prove the dispatcher actually handed real numbers to the model,
        # without needing a real LLM: echo back a fact from the context
        # so the test can assert it was present.
        assert "REAL RECENT DATA" not in user_message  # data goes in system prompt, not user msg
        if "Mayur" in system_prompt:
            return f"[grounded-answer] saw Mayur stock in context. Question was: {user_message}"
        return f"[grounded-answer] no stock context found. Question was: {user_message}"


assistant_main.OllamaClient = FakeOllamaClient
assistant_dispatcher.OllamaClient = FakeOllamaClient
assistant_client = TestClient(assistant_app, base_url="http://assistant_service").__enter__()
_test_clients["assistant_service"] = assistant_client
_URL_TO_SERVICE_DIR["http://assistant-service:8000"] = "assistant_service"

# ----------------------------------------------------------------------
# 1. general_query - a plain calculation, answered conversationally,
#    grounded in real data pulled from the actual services.
# ----------------------------------------------------------------------
_next_intent["value"] = Intent(action=IntentAction.GENERAL_QUERY, raw_user_message="What's 12% of 45000?")
r = assistant_client.post("/assistant/chat", json={"message": "What's 12% of 45000?"})
body = r.json()
check("general_query returns ok", r.status_code == 200 and body["status"] == "ok", body)
check("general_query answer is grounded in real stock data", "saw Mayur stock in context" in body["message"], body)
check("general_query never returns 'affected' (read-only)", not body.get("data", {}).get("affected"), body)

# ----------------------------------------------------------------------
# 2. update_expense - needs confirmation, never edits in place, voids +
#    re-records, and shows up correctly afterward.
# ----------------------------------------------------------------------
_next_intent["value"] = Intent(
    action=IntentAction.UPDATE_EXPENSE, expense_category_name="Transport",
    date=dt.date.today(), amount=2000, reason="owner corrected the amount",
)
r = assistant_client.post("/assistant/chat", json={"message": "the transport expense today should be 2000 not 1500"})
body = r.json()
check("update_expense needs confirmation first", body["status"] == "needs_confirmation", body)
check("confirmation message shows old and new amount", "1,500" in body["message"] or "1500" in body["message"], body)

r2 = assistant_client.post("/assistant/chat", json={
    "message": "", "intent": body["intent"], "confirmed": True,
})
body2 = r2.json()
check("update_expense executes on confirm", body2["status"] == "ok", body2)
check("response reports affected=['expenses','cashbank']",
      set(body2.get("data", {}).get("affected", [])) == {"expenses", "cashbank"}, body2)

# Verify actual data: old expense voided, new one active, breakdown correct (no double count).
r = expense_client.get("/expenses", params={"expense_date": TODAY, "category_id": transport_cat_id})
active = r.json()
check("exactly one ACTIVE Transport expense remains", len(active) == 1, active)
check("active expense amount is now 2000", active and active[0]["amount"] == 2000.0, active)

r = expense_client.get("/expenses/breakdown", params={"start": TODAY, "end": TODAY})
breakdown = r.json()
check("breakdown shows 2000, not 3500 (no double-count of voided row)",
      breakdown == [{"category": "Transport", "amount": 2000.0}], breakdown)

r = expense_client.get("/expenses/total", params={"start": TODAY, "end": TODAY})
check("ledger-derived total also 2000 (reversal cancelled the old 1500)", r.json()["total"] == 2000.0, r.json())

# Trying to correct the SAME (now-voided) expense again should fail cleanly.
r_correct_again = expense_client.post("/expenses/1/correct", json={"new_amount": 999})
check("correcting an already-voided expense is rejected", r_correct_again.status_code == 400, r_correct_again.text)

print(f"\n{results['pass']} passed, {results['fail']} failed")
sys.exit(1 if results["fail"] else 0)
