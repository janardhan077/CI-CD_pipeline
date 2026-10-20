"""
Dispatcher.

Turns a validated Intent into exactly one call to another service's
REST API. This is where the AI safety rules are actually enforced in
code, not just in the prompt:

  - Every entity reference is resolved by exact/case-insensitive name
    match against data fetched from the owning service. Zero matches
    or multiple matches never guesses - it asks (AmbiguousCommandError
    -> clarification).
  - Every write goes through the SAME REST endpoints the UI's forms
    use (POST /sales, POST /expenses, ...) - the AI has no separate,
    looser code path, and no database connection of its own at all.
  - `reverse_transaction` NEVER executes on the first call. It always
    returns a `needs_confirmation` result describing exactly what would
    happen; only a second call with `confirmed=True` (which the API
    layer requires the user to explicitly trigger) executes it.
"""
import datetime as dt
from dataclasses import dataclass, field

from common.core.enums import ActorType, PaymentMethod
from common.core.exceptions import AmbiguousCommandError, ValidationError, NotFoundError
from common.ledger_client import LedgerClient

from app import clients, prompts
from app.ollama_client import OllamaClient, OllamaUnavailableError
from app.schemas import Intent, IntentAction


@dataclass
class DispatchResult:
    status: str  # "ok" | "needs_clarification" | "needs_confirmation" | "error"
    message: str
    data: dict = field(default_factory=dict)


def _resolve_by_name(items: list[dict], name: str, label: str) -> dict:
    if not name:
        raise AmbiguousCommandError(f"No {label} name was given.")
    needle = name.strip().lower()

    exact = [it for it in items if it["name"].strip().lower() == needle]
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        options = ", ".join(it["name"] for it in exact)
        raise AmbiguousCommandError(
            f"More than one {label} matches '{name}': {options}. "
            f"Please specify which one (e.g. add a location or nickname)."
        )

    # No exact match - fall back to substring, but still refuse to
    # guess if that's ambiguous too.
    loose = [it for it in items if needle in it["name"].strip().lower()]
    if len(loose) == 0:
        raise AmbiguousCommandError(
            f"No {label} named '{name}' found. Add them first, or check the spelling."
        )
    if len(loose) > 1:
        options = ", ".join(it["name"] for it in loose)
        raise AmbiguousCommandError(
            f"More than one {label} matches '{name}': {options}. "
            f"Please specify which one (e.g. add a location or nickname)."
        )
    return loose[0]


class IntentDispatcher:
    def __init__(self, ledger: LedgerClient | None = None):
        self.ledger = ledger or LedgerClient()

    def dispatch(self, intent: Intent, confirmed: bool = False) -> DispatchResult:
        try:
            return self._dispatch(intent, confirmed=confirmed)
        except AmbiguousCommandError as exc:
            return DispatchResult(status="needs_clarification", message=str(exc))
        except (ValidationError, NotFoundError) as exc:
            return DispatchResult(status="error", message=str(exc))

    def _dispatch(self, intent: Intent, confirmed: bool) -> DispatchResult:
        action = intent.action

        if action == IntentAction.CLARIFY:
            return DispatchResult(
                status="needs_clarification",
                message=intent.clarifying_question or "Could you provide more detail?",
            )

        if action == IntentAction.UNSUPPORTED:
            return DispatchResult(
                status="error",
                message="That's outside what IN-ON can help with - I can record sales, "
                        "expenses, credit payments, purchases, stock adjustments, and "
                        "answer questions about stock, credit, sales, and expenses.",
            )

        handlers = {
            IntentAction.RECORD_SALE: self._record_sale,
            IntentAction.RECORD_EXPENSE: self._record_expense,
            IntentAction.RECORD_CREDIT_PAYMENT: self._record_credit_payment,
            IntentAction.RECORD_PURCHASE: self._record_purchase,
            IntentAction.RECORD_STOCK_ADJUSTMENT: self._record_stock_adjustment,
            IntentAction.QUERY_STOCK: self._query_stock,
            IntentAction.QUERY_CUSTOMER_CREDIT: self._query_customer_credit,
            IntentAction.QUERY_TOTAL_CREDIT: self._query_total_credit,
            IntentAction.QUERY_SALES_TOTAL: self._query_sales_total,
            IntentAction.QUERY_EXPENSE_TOTAL: self._query_expense_total,
            IntentAction.GENERATE_REPORT: self._generate_report,
        }
        if action in handlers:
            return handlers[action](intent)
        if action == IntentAction.REVERSE_TRANSACTION:
            return self._reverse_transaction(intent, confirmed=confirmed)
        if action == IntentAction.UPDATE_EXPENSE:
            return self._update_expense(intent, confirmed=confirmed)
        if action == IntentAction.GENERAL_QUERY:
            return self._general_query(intent)

        return DispatchResult(status="error", message=f"Unhandled action: {action}")

    # ------------------------------------------------------------------ writes
    def _record_sale(self, intent: Intent) -> DispatchResult:
        if not intent.customer_name:
            raise AmbiguousCommandError("Which customer is this sale for?")
        if not intent.stock_type_name:
            raise AmbiguousCommandError("Which stock type was sold (e.g. Mayur, MK, MR)?")
        if intent.quantity is None:
            raise AmbiguousCommandError("How many bags were sold?")
        if intent.total_amount is None and intent.rate is None:
            raise AmbiguousCommandError("What was the total sale amount (or rate per bag)?")

        customer = _resolve_by_name(clients.list_customers(), intent.customer_name, "customer")
        stock_type = _resolve_by_name(clients.list_stock_types(), intent.stock_type_name, "stock type")

        rate = intent.rate
        if rate is None:
            rate = round(intent.total_amount / intent.quantity, 2)

        sale = clients.create_sale(
            sale_date=intent.date or dt.date.today(),
            customer_id=customer["id"],
            stock_type_id=stock_type["id"],
            quantity=intent.quantity,
            rate=rate,
            cash_received=intent.cash_received or 0,
            bank_received=intent.bank_received or 0,
            notes=intent.notes,
            created_by=ActorType.AI.value,
        )

        return DispatchResult(
            status="ok",
            message=(
                f"Recorded: {sale['quantity']} bag(s) of {stock_type['name']} to "
                f"{customer['name']} for \u20b9{sale['total_amount']:,.2f}. "
                f"Received \u20b9{sale['amount_received']:,.2f}"
                + (f", credit \u20b9{sale['credit_amount']:,.2f}." if sale['credit_amount'] > 0 else ".")
            ),
            data={"sale_id": sale["id"], "affected": ["stock", "sales", "cashbank", "credit"]},
        )

    def _record_expense(self, intent: Intent) -> DispatchResult:
        if intent.amount is None:
            raise AmbiguousCommandError("What is the expense amount?")
        if not intent.expense_category_name:
            raise AmbiguousCommandError("What is the expense category?")

        category = _resolve_by_name(
            clients.list_expense_categories(), intent.expense_category_name, "expense category"
        )
        expense = clients.create_expense(
            expense_date=intent.date or dt.date.today(),
            category_id=category["id"],
            amount=intent.amount,
            payment_method=(PaymentMethod.BANK if intent.bank_received else PaymentMethod.CASH).value,
            description=intent.notes,
            created_by=ActorType.AI.value,
        )
        return DispatchResult(
            status="ok",
            message=f"Recorded \u20b9{expense['amount']:,.2f} expense under {category['name']}.",
            data={"expense_id": expense["id"], "affected": ["expenses", "cashbank"]},
        )

    def _record_credit_payment(self, intent: Intent) -> DispatchResult:
        if not intent.customer_name:
            raise AmbiguousCommandError("Which customer made this payment?")
        if intent.amount is None:
            raise AmbiguousCommandError("How much did they pay?")

        customer = _resolve_by_name(clients.list_customers(), intent.customer_name, "customer")
        payment = clients.create_credit_payment(
            customer["id"],
            payment_date=intent.date or dt.date.today(),
            amount=intent.amount,
            created_by=ActorType.AI.value,
        )
        remaining = clients.get_customer_balance(customer["id"])["outstanding"]
        return DispatchResult(
            status="ok",
            message=f"Recorded \u20b9{payment['amount']:,.2f} payment from {customer['name']}. "
                    f"Remaining balance: \u20b9{remaining:,.2f}.",
            data={"payment_id": payment["id"], "remaining_balance": remaining, "affected": ["credit", "cashbank"]},
        )

    def _record_purchase(self, intent: Intent) -> DispatchResult:
        if not intent.stock_type_name:
            raise AmbiguousCommandError("What stock type was purchased?")
        if intent.quantity is None:
            raise AmbiguousCommandError("How many bags were purchased?")
        if intent.rate is None and intent.total_amount is None:
            raise AmbiguousCommandError("What was the rate or total amount for this purchase?")

        stock_type = _resolve_by_name(clients.list_stock_types(), intent.stock_type_name, "stock type")
        rate = intent.rate or round(intent.total_amount / intent.quantity, 2)

        purchase = clients.create_purchase(
            purchase_date=intent.date or dt.date.today(),
            stock_type_id=stock_type["id"],
            quantity=intent.quantity,
            rate=rate,
            amount_paid=intent.cash_received or intent.total_amount,
            created_by=ActorType.AI.value,
        )
        return DispatchResult(
            status="ok",
            message=f"Recorded purchase: {intent.quantity} bag(s) of "
                    f"{stock_type['name']} for \u20b9{purchase['total_amount']:,.2f}.",
            data={"purchase_id": purchase["id"], "affected": ["stock", "cashbank"]},
        )

    def _record_stock_adjustment(self, intent: Intent) -> DispatchResult:
        if not intent.stock_type_name:
            raise AmbiguousCommandError("Which stock type needs adjusting?")
        if intent.quantity is None:
            raise AmbiguousCommandError(
                "What's the adjustment quantity - e.g. 'used 400 bags' or 'found 15 extra bags'?"
            )

        stock_type = _resolve_by_name(clients.list_stock_types(), intent.stock_type_name, "stock type")
        adjustment = clients.create_stock_adjustment(
            adjustment_date=intent.date or dt.date.today(),
            stock_type_id=stock_type["id"],
            quantity_delta=intent.quantity,
            reason=intent.reason or "AI-recorded adjustment",
            created_by=ActorType.AI.value,
        )
        direction = "used from" if intent.quantity < 0 else "added to"
        return DispatchResult(
            status="ok",
            message=f"Recorded: {abs(intent.quantity):g} {stock_type['unit']}(s) {direction} "
                    f"{stock_type['name']}"
                    f"{f' ({intent.reason})' if intent.reason else ''}. "
                    f"This is now reflected in stock, today's report, and the ledger.",
            data={"adjustment_id": adjustment["id"], "affected": ["stock"]},
        )

    # ------------------------------------------------------------------ reads
    def _query_stock(self, intent: Intent) -> DispatchResult:
        if intent.stock_type_name:
            stock_type = _resolve_by_name(clients.list_stock_types(), intent.stock_type_name, "stock type")
            qty = self.ledger.get_stock_by_type(stock_type["id"])
            return DispatchResult(
                status="ok", message=f"{stock_type['name']}: {qty} {stock_type['unit']}(s).",
                data={"stock_type": stock_type["name"], "quantity": qty},
            )
        snapshot = clients.get_stock_snapshot()
        lines = [f"{s['name']}: {s['quantity']} {s['unit']}(s)" for s in snapshot]
        total = sum(s["quantity"] for s in snapshot)
        return DispatchResult(
            status="ok",
            message="Current stock \u2014 " + "; ".join(lines) + f". Total: {total}.",
            data={"snapshot": snapshot},
        )

    def _query_customer_credit(self, intent: Intent) -> DispatchResult:
        if not intent.customer_name:
            raise AmbiguousCommandError("Which customer?")
        customer = _resolve_by_name(clients.list_customers(), intent.customer_name, "customer")
        balance = clients.get_customer_balance(customer["id"])["outstanding"]
        return DispatchResult(
            status="ok",
            message=f"{customer['name']} owes \u20b9{balance:,.2f}." if balance > 0
                    else f"{customer['name']} has no outstanding balance.",
            data={"customer": customer["name"], "outstanding": balance},
        )

    def _query_total_credit(self, intent: Intent) -> DispatchResult:
        balances = clients.get_all_customer_outstanding()
        total = sum(b["outstanding"] for b in balances)
        return DispatchResult(
            status="ok",
            message=f"Total outstanding credit: \u20b9{total:,.2f} across {len(balances)} customer(s).",
            data={"total": total, "customers": balances},
        )

    def _query_sales_total(self, intent: Intent) -> DispatchResult:
        target_date = intent.date or dt.date.today()
        sales = clients.get_sales_for_date(target_date)
        total = sum(float(s["total_amount"]) for s in sales)
        bags = sum(float(s["quantity"]) for s in sales)
        return DispatchResult(
            status="ok",
            message=f"Sales on {target_date.strftime('%d/%m/%Y')}: {bags} bags, \u20b9{total:,.2f} total.",
            data={"date": str(target_date), "total": total, "bags": bags},
        )

    def _query_expense_total(self, intent: Intent) -> DispatchResult:
        target_date = intent.date or dt.date.today()
        total = clients.get_expense_total(target_date, target_date)
        return DispatchResult(
            status="ok",
            message=f"Expenses on {target_date.strftime('%d/%m/%Y')}: \u20b9{total:,.2f}.",
            data={"date": str(target_date), "total": total},
        )

    def _generate_report(self, intent: Intent) -> DispatchResult:
        target_date = intent.date or dt.date.today()
        report_text = clients.get_daily_report_text(target_date)
        return DispatchResult(status="ok", message=report_text, data={"date": str(target_date)})

    # ------------------------------------------------------------------ destructive
    def _reverse_transaction(self, intent: Intent, confirmed: bool) -> DispatchResult:
        if intent.reference_transaction_id is None:
            raise AmbiguousCommandError(
                "Which transaction should be reversed? Please give the transaction ID "
                "(visible in the transaction history/report)."
            )

        original = self.ledger.get_transaction(intent.reference_transaction_id)

        if not confirmed:
            return DispatchResult(
                status="needs_confirmation",
                message=(
                    f"This will reverse transaction #{original['id']}: "
                    f"{original['txn_type']} of \u20b9{original['amount']} "
                    f"({original['description'] or 'no description'}) dated "
                    f"{original['txn_datetime'][:10]}. "
                    f"Confirm to proceed - this cannot be silently undone again."
                ),
                data={"transaction_id": original["id"]},
            )

        reversal = self.ledger.reverse_transaction(
            original["id"], reason=intent.reason or "Reversed via AI assistant, user-confirmed",
            created_by=ActorType.AI,
        )
        return DispatchResult(
            status="ok",
            message=f"Reversed transaction #{original['id']} (new reversal record #{reversal['id']}).",
            data={"reversal_id": reversal["id"], "affected": ["stock", "sales", "cashbank", "credit", "expenses"]},
        )

    # ------------------------------------------------------------------ correction (never a silent edit)
    def _update_expense(self, intent: Intent, confirmed: bool) -> DispatchResult:
        if not intent.expense_category_name:
            raise AmbiguousCommandError("Which expense category needs correcting?")
        if intent.amount is None:
            raise AmbiguousCommandError("What should the corrected amount be?")

        category = _resolve_by_name(
            clients.list_expense_categories(), intent.expense_category_name, "expense category"
        )
        target_date = intent.date or dt.date.today()
        candidates = clients.get_expenses(expense_date=target_date, category_id=category["id"])

        if len(candidates) == 0:
            raise AmbiguousCommandError(
                f"No {category['name']} expense found on {target_date} to correct. "
                f"Check the date and category, or record it as a new expense instead."
            )
        if len(candidates) > 1:
            options = ", ".join(f"\u20b9{c['amount']:,.2f} (id {c['id']})" for c in candidates)
            raise AmbiguousCommandError(
                f"Found {len(candidates)} {category['name']} expenses on {target_date}: {options}. "
                f"Mention the original amount so I know which one you mean."
            )
        old = candidates[0]

        if old["amount"] == intent.amount:
            return DispatchResult(
                status="ok",
                message=f"The {category['name']} expense on {target_date} is already "
                        f"\u20b9{intent.amount:,.2f} - nothing to change.",
            )

        if not confirmed:
            return DispatchResult(
                status="needs_confirmation",
                message=(
                    f"This will correct the {category['name']} expense on {target_date} from "
                    f"\u20b9{old['amount']:,.2f} to \u20b9{intent.amount:,.2f}. The original entry "
                    f"is kept for the audit trail, not deleted - only its ledger effect is reversed "
                    f"and a new corrected entry is added. Confirm to proceed."
                ),
                data={"expense_id": old["id"], "old_amount": old["amount"], "new_amount": intent.amount},
            )

        result = clients.correct_expense(
            old["id"], new_amount=intent.amount,
            reason=intent.reason or "Corrected via assistant, user-confirmed",
            created_by=ActorType.AI.value,
        )
        return DispatchResult(
            status="ok",
            message=f"Corrected: {category['name']} expense on {target_date} is now "
                    f"\u20b9{result['new_amount']:,.2f} (was \u20b9{result['old_amount']:,.2f}).",
            data={"old_expense_id": result["old_expense_id"], "new_expense_id": result["new_expense_id"],
                  "affected": ["expenses", "cashbank"]},
        )

    # ------------------------------------------------------------------ general / read-only chat
    def _general_query(self, intent: Intent) -> DispatchResult:
        """Calculations, predictions/estimates, and general shop-related
        questions. This path NEVER calls a write endpoint - it only
        reads data to ground an answer, then hands the model's own
        words straight back. See app/ollama_client.py's
        `answer_freeform` and app/prompts.py's
        `GENERAL_ASSISTANT_SYSTEM_PROMPT` docstrings for the safety
        reasoning."""
        question = intent.raw_user_message or "The owner asked a general question."
        try:
            context = clients.get_recent_business_summary()
        except Exception:
            context = ""
        try:
            answer = OllamaClient().answer_freeform(
                prompts.build_general_query_prompt(context), question
            )
        except OllamaUnavailableError as exc:
            return DispatchResult(status="error", message=str(exc))
        return DispatchResult(status="ok", message=answer)
