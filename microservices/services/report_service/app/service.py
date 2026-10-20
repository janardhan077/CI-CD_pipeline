"""
ReportService - owns no table of its own.

Generates the daily report purely from the Ledger service and the
other services' read APIs - never from any separately-maintained
running total. This is what lets IN-ON answer "why is today's cash X"
honestly: the report and a from-scratch ledger query agree by
construction, the same guarantee the monolith had, just assembled
across a network instead of in one process.
"""
import datetime as dt
from dataclasses import dataclass, field

from common.core.enums import TxnType, Account, Direction
from common.ledger_client import LedgerClient

from app import clients


@dataclass
class DailyReport:
    report_date: dt.date
    day_name: str

    total_bags_sold: float = 0
    total_sales_amount: float = 0
    cash_sales: float = 0
    bank_sales: float = 0
    credit_sales: float = 0

    credit_received: float = 0
    outstanding_credit_total: float = 0

    opening_cash: float = 0
    cash_received: float = 0
    cash_expenses: float = 0
    closing_cash: float = 0

    opening_bank: float = 0
    bank_received: float = 0
    bank_payments: float = 0
    closing_bank: float = 0

    total_expenses: float = 0
    expense_breakdown: list = field(default_factory=list)

    opening_stock: float = 0
    stock_purchased: float = 0
    stock_sold: float = 0
    closing_stock: float = 0
    stock_by_type: list = field(default_factory=list)

    customer_credit_balances: list = field(default_factory=list)

    def as_text(self) -> str:
        """Render in the same style as the owner's original manual report."""
        lines = [
            "IN-ON DAILY BUSINESS REPORT",
            "",
            f"Date: {self.report_date.strftime('%d/%m/%Y')}",
            f"Day: {self.day_name}",
            "",
            "SALES",
            f"Total bags: {self.total_bags_sold}",
            f"Total sales: \u20b9{self.total_sales_amount:,.2f}",
            f"Cash sales: \u20b9{self.cash_sales:,.2f}",
            f"Bank sales: \u20b9{self.bank_sales:,.2f}",
            f"Credit sales: \u20b9{self.credit_sales:,.2f}",
            "",
            "RECEIVABLES",
            f"Credit received: \u20b9{self.credit_received:,.2f}",
            f"Outstanding credit (total): \u20b9{self.outstanding_credit_total:,.2f}",
            "",
            "FINANCE (CASH)",
            f"Opening cash: \u20b9{self.opening_cash:,.2f}",
            f"Cash received: \u20b9{self.cash_received:,.2f}",
            f"Cash expenses: \u20b9{self.cash_expenses:,.2f}",
            f"Closing cash: \u20b9{self.closing_cash:,.2f}",
            "",
            "FINANCE (BANK)",
            f"Opening bank: \u20b9{self.opening_bank:,.2f}",
            f"Bank received: \u20b9{self.bank_received:,.2f}",
            f"Bank payments: \u20b9{self.bank_payments:,.2f}",
            f"Closing bank: \u20b9{self.closing_bank:,.2f}",
            "",
            "EXPENSES",
            f"Total expenses: \u20b9{self.total_expenses:,.2f}",
        ]
        for item in self.expense_breakdown:
            lines.append(f"  - {item['category']}: \u20b9{item['amount']:,.2f}")
        lines += ["", "STOCK", f"Opening stock: {self.opening_stock}",
                  f"Stock purchased: {self.stock_purchased}",
                  f"Stock sold: {self.stock_sold}",
                  f"Closing stock: {self.closing_stock}"]
        for item in self.stock_by_type:
            lines.append(f"  - {item['name']}: {item['quantity']}")
        lines += ["", "CUSTOMER CREDIT"]
        for c in self.customer_credit_balances:
            lines.append(f"  - {c['name']}: \u20b9{c['outstanding']:,.2f}")
        lines += [
            "",
            "SUMMARY",
            f"Total sales: \u20b9{self.total_sales_amount:,.2f}",
            f"Total expenses: \u20b9{self.total_expenses:,.2f}",
            f"Cash in hand: \u20b9{self.closing_cash:,.2f}",
            f"Bank balance: \u20b9{self.closing_bank:,.2f}",
            f"Outstanding credit: \u20b9{self.outstanding_credit_total:,.2f}",
            f"Available stock: {self.closing_stock}",
        ]
        return "\n".join(lines)


class ReportService:
    def __init__(self, ledger: LedgerClient | None = None):
        self.ledger = ledger or LedgerClient()

    def daily_report(self, report_date: dt.date) -> DailyReport:
        day_before = report_date - dt.timedelta(days=1)
        txns = self.ledger.get_transactions_between(report_date, report_date)

        sales_today = clients.get_sales_for_date(report_date)
        total_bags = sum(float(s["quantity"]) for s in sales_today)
        total_sales_amount = sum(float(s["total_amount"]) for s in sales_today)
        cash_sales = sum(float(s["cash_received"]) for s in sales_today)
        bank_sales = sum(float(s["bank_received"]) for s in sales_today)
        credit_sales = sum(float(s["credit_amount"]) for s in sales_today)

        credit_received = sum(
            float(t["amount"]) for t in txns
            if t["txn_type"] == TxnType.CREDIT_PAYMENT.value
            and t["account"] in (Account.CASH.value, Account.BANK.value)
            and t["direction"] == Direction.IN.value
        )

        opening_cash = self.ledger.get_cash_balance(as_of=day_before)
        closing_cash = self.ledger.get_cash_balance(as_of=report_date)
        cash_received = sum(
            float(t["amount"]) for t in txns
            if t["account"] == Account.CASH.value and t["direction"] == Direction.IN.value
        )
        cash_expenses = sum(
            float(t["amount"]) for t in txns
            if t["account"] == Account.CASH.value and t["direction"] == Direction.OUT.value
            and t["txn_type"] == TxnType.EXPENSE.value
        )

        opening_bank = self.ledger.get_bank_balance(as_of=day_before)
        closing_bank = self.ledger.get_bank_balance(as_of=report_date)
        bank_received = sum(
            float(t["amount"]) for t in txns
            if t["account"] == Account.BANK.value and t["direction"] == Direction.IN.value
        )
        bank_payments = sum(
            float(t["amount"]) for t in txns
            if t["account"] == Account.BANK.value and t["direction"] == Direction.OUT.value
        )

        total_expenses = clients.get_expense_total(report_date, report_date)
        expense_breakdown = clients.get_expense_breakdown(report_date, report_date)

        opening_stock = self.ledger.get_total_stock(as_of=day_before)
        closing_stock = self.ledger.get_total_stock(as_of=report_date)
        stock_purchased = sum(
            float(t["amount"]) for t in txns
            if t["account"] == Account.STOCK.value and t["direction"] == Direction.IN.value
        )
        stock_sold = sum(
            float(t["amount"]) for t in txns
            if t["account"] == Account.STOCK.value and t["direction"] == Direction.OUT.value
        )
        stock_by_type = clients.get_stock_snapshot(as_of=report_date)

        customer_credit_balances = clients.get_all_customer_outstanding(as_of=report_date)
        outstanding_credit_total = sum(c["outstanding"] for c in customer_credit_balances)

        return DailyReport(
            report_date=report_date,
            day_name=report_date.strftime("%A"),
            total_bags_sold=total_bags,
            total_sales_amount=total_sales_amount,
            cash_sales=cash_sales,
            bank_sales=bank_sales,
            credit_sales=credit_sales,
            credit_received=credit_received,
            outstanding_credit_total=outstanding_credit_total,
            opening_cash=opening_cash,
            cash_received=cash_received,
            cash_expenses=cash_expenses,
            closing_cash=closing_cash,
            opening_bank=opening_bank,
            bank_received=bank_received,
            bank_payments=bank_payments,
            closing_bank=closing_bank,
            total_expenses=total_expenses,
            expense_breakdown=expense_breakdown,
            opening_stock=opening_stock,
            stock_purchased=stock_purchased,
            stock_sold=stock_sold,
            closing_stock=closing_stock,
            stock_by_type=stock_by_type,
            customer_credit_balances=customer_credit_balances,
        )
