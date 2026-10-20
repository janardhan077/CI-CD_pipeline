// IN-ON frontend - plain JS, no build step, talks to the FastAPI backend
// running on the same origin. Local-first: nothing here calls out to the
// internet except the same-origin API calls to this app's own backend
// (and Google Fonts, loaded once via styles.css).

const API = "";

async function api(path, options = {}) {
  const res = await fetch(API + path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  let body = null;
  try { body = await res.json(); } catch (e) { /* no body */ }
  if (!res.ok) {
    const detail = body && (body.detail || body.error) ? (body.detail || body.error) : res.statusText;
    throw new Error(detail);
  }
  return body;
}

function fmtMoney(n) {
  const v = Number(n || 0);
  return "\u20B9" + v.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}
function fmtQty(n) {
  const v = Number(n || 0);
  return v % 1 === 0 ? String(v) : v.toFixed(2);
}
function todayStr() {
  const d = new Date();
  return d.toISOString().slice(0, 10);
}
function timeStr() {
  return new Date().toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" });
}
function el(html) {
  const t = document.createElement("template");
  t.innerHTML = html.trim();
  return t.content.firstChild;
}
function showMsg(container, type, text) {
  const box = el(`<div class="msg ${type}">${text}</div>`);
  container.prepend(box);
  setTimeout(() => box.remove(), 6000);
}

// ---------------------------------------------------------------- TOASTS
// A toast confirms, in the corner of the screen, that something just
// changed - used after every write (form submit or assistant action)
// so the person always sees confirmation the actual data changed, not
// just that a request was sent.
function toast(type, text) {
  const stack = document.getElementById("toast-stack");
  const t = el(`<div class="toast ${type}"><span>${text}</span><span class="close">\u2715</span></div>`);
  t.querySelector(".close").addEventListener("click", () => t.remove());
  stack.appendChild(t);
  setTimeout(() => {
    t.style.animation = "toast-out 0.2s ease forwards";
    setTimeout(() => t.remove(), 200);
  }, 4500);
}

// ---------------------------------------------------------------- LIVE TICKER
// Always-visible strip at the top of every page. This is "the sheet"
// updating live: whenever a sale/expense/purchase/adjustment/payment
// is recorded - through a form OR through the assistant chat - this
// re-fetches the real numbers from the real services and flashes
// whichever values changed, so the person can see the write actually
// landed without leaving whatever page they're on.
let lastTicker = null;

async function refreshTicker() {
  try {
    const [balances, snapshot, outstanding] = await Promise.all([
      api("/cashbank/balances"),
      api("/stock/snapshot"),
      api("/customers/credit/outstanding"),
    ]);
    const totalStock = snapshot.reduce((s, r) => s + Number(r.quantity || 0), 0);
    const totalCredit = outstanding.reduce((s, r) => s + Number(r.outstanding || 0), 0);
    const next = { cash: balances.cash, bank: balances.bank, stock: totalStock, credit: totalCredit };

    setTickerValue("tk-cash", fmtMoney(next.cash), lastTicker && next.cash !== lastTicker.cash);
    setTickerValue("tk-bank", fmtMoney(next.bank), lastTicker && next.bank !== lastTicker.bank);
    setTickerValue("tk-stock", fmtQty(next.stock) + " bag(s)", lastTicker && next.stock !== lastTicker.stock);
    setTickerValue("tk-credit", fmtMoney(next.credit), lastTicker && next.credit !== lastTicker.credit);
    document.getElementById("tk-refreshed").textContent = "Updated " + timeStr();
    setSync(true);
    lastTicker = next;
    return next;
  } catch (err) {
    setSync(false);
    return null;
  }
}
function setTickerValue(id, text, flash) {
  const node = document.getElementById(id);
  if (!node) return;
  node.textContent = text;
  if (flash) {
    node.classList.remove("flash");
    void node.offsetWidth; // restart animation
    node.classList.add("flash");
  }
}
function setSync(ok) {
  const dot = document.querySelector(".sync-dot");
  const label = document.getElementById("sync-label");
  if (!dot || !label) return;
  dot.classList.toggle("stale", !ok);
  label.textContent = ok ? "Live" : "Offline";
}

// Areas a write can affect, and which page(s) should re-render if the
// person is currently looking at them. The ticker above always
// refreshes regardless of the active page.
const AFFECTED_TO_PAGES = {
  stock: ["stock", "dashboard"],
  sales: ["sales", "dashboard"],
  cashbank: ["cashbank", "dashboard"],
  credit: ["customers", "dashboard"],
  expenses: ["expenses", "dashboard"],
};

async function notifyDataChanged(affected) {
  await refreshTicker();
  const pagesToRefresh = new Set();
  (affected || []).forEach((area) => (AFFECTED_TO_PAGES[area] || []).forEach((p) => pagesToRefresh.add(p)));
  if (currentPage && pagesToRefresh.has(currentPage) && currentPage !== "assistant") {
    navigate(currentPage, { silent: true });
  }
}

// ---------------------------------------------------------------- routing
const PAGES = {
  dashboard: renderDashboard,
  sales: renderSales,
  expenses: renderExpenses,
  customers: renderCustomers,
  stock: renderStock,
  cashbank: renderCashBank,
  reports: renderReports,
  excel: renderExcel,
  assistant: renderAssistant,
};

let currentPage = null;

function setActiveTab(page) {
  document.querySelectorAll(".nav-tab").forEach((t) => {
    t.classList.toggle("active", t.dataset.page === page);
  });
}

function skeletonHTML(lines = 4) {
  return `<div class="card">${"<div class=\"skeleton\"></div>".repeat(lines)}</div>`;
}

async function navigate(page, opts = {}) {
  currentPage = page;
  setActiveTab(page);
  closeMobileNav();
  const content = document.getElementById("page-content");
  if (!opts.silent) content.innerHTML = skeletonHTML();
  try {
    await PAGES[page](content);
  } catch (err) {
    content.innerHTML = `<div class="msg error">Could not load this page: ${err.message}</div>`;
  }
}

document.querySelectorAll(".nav-tab").forEach((tab) => {
  tab.addEventListener("click", () => navigate(tab.dataset.page));
});

// ---------------------------------------------------------------- mobile nav
function openMobileNav() {
  document.getElementById("sidebar").classList.add("open");
  document.getElementById("scrim").classList.add("open");
}
function closeMobileNav() {
  document.getElementById("sidebar").classList.remove("open");
  document.getElementById("scrim").classList.remove("open");
}
document.getElementById("nav-toggle").addEventListener("click", openMobileNav);
document.getElementById("scrim").addEventListener("click", closeMobileNav);

// ---------------------------------------------------------------- init
navigate("dashboard");
refreshTicker();
setInterval(refreshTicker, 30000); // background refresh so the ticker doesn't go stale even if nothing is clicked

// Wraps a form's submit handler so the button shows a spinner and any
// thrown error becomes a toast + inline message, consistently.
function bindForm(form, container, handler) {
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const btn = form.querySelector("button[type=submit]");
    btn && btn.classList.add("loading");
    btn && (btn.disabled = true);
    try {
      await handler(e);
    } catch (err) {
      showMsg(container, "error", err.message);
      toast("error", err.message);
    } finally {
      btn && btn.classList.remove("loading");
      btn && (btn.disabled = false);
    }
  });
}

// ---------------------------------------------------------------- DASHBOARD
async function renderDashboard(root) {
  const date = todayStr();
  let report;
  try {
    report = await api(`/reports/daily?report_date=${date}`);
  } catch (err) {
    root.innerHTML = `
      <h1 class="page-title">Dashboard</h1>
      <p class="page-sub">Today, ${new Date().toDateString()}</p>
      <div class="msg info">No data yet for today — record a sale, expense, or purchase to see it here.</div>`;
    return;
  }

  root.innerHTML = `
    <h1 class="page-title">Dashboard</h1>
    <p class="page-sub">${report.day_name}, ${date}</p>
    <div class="stat-grid">
      <div class="stat good"><div class="stat-label">Cash in hand</div><div class="stat-value">${fmtMoney(report.closing_cash)}</div></div>
      <div class="stat good"><div class="stat-label">Bank balance</div><div class="stat-value">${fmtMoney(report.closing_bank)}</div></div>
      <div class="stat warn"><div class="stat-label">Outstanding credit</div><div class="stat-value">${fmtMoney(report.outstanding_credit_total)}</div></div>
      <div class="stat"><div class="stat-label">Available stock</div><div class="stat-value">${fmtQty(report.closing_stock)}</div></div>
      <div class="stat"><div class="stat-label">Today's sales</div><div class="stat-value">${fmtMoney(report.total_sales_amount)}</div></div>
      <div class="stat"><div class="stat-label">Today's expenses</div><div class="stat-value">${fmtMoney(report.total_expenses)}</div></div>
    </div>
    <div class="two-col">
      <div class="card">
        <h3>Today's Sales Breakdown</h3>
        <table>
          <tr><td>Bags sold</td><td class="num mono">${fmtQty(report.total_bags_sold)}</td></tr>
          <tr><td>Cash sales</td><td class="num mono">${fmtMoney(report.cash_sales)}</td></tr>
          <tr><td>Bank sales</td><td class="num mono">${fmtMoney(report.bank_sales)}</td></tr>
          <tr><td>Credit extended</td><td class="num mono">${fmtMoney(report.credit_sales)}</td></tr>
          <tr><td>Credit received</td><td class="num mono">${fmtMoney(report.credit_received)}</td></tr>
        </table>
      </div>
      <div class="card">
        <h3>Customer Credit (Top Balances)</h3>
        <table>
          <tr><th>Customer</th><th class="num">Outstanding</th></tr>
          ${(report.customer_credit_balances || []).slice(0, 8).map(c =>
            `<tr><td>${c.name}</td><td class="num mono">${fmtMoney(c.outstanding)}</td></tr>`
          ).join("") || `<tr><td colspan="2" class="hint">No outstanding credit.</td></tr>`}
        </table>
      </div>
    </div>
    <p class="hint">Ask the <a href="#" id="dash-assistant-link">Assistant</a> to record things in plain English — "used 400 bags of Mayur today", "sold 5 bags to Ramesh for 3000" — and this dashboard updates immediately.</p>`;

  const link = document.getElementById("dash-assistant-link");
  if (link) link.addEventListener("click", (e) => { e.preventDefault(); navigate("assistant"); });
}

// ---------------------------------------------------------------- SALES
async function renderSales(root) {
  const [customers, stockTypes] = await Promise.all([
    api("/customers"), api("/stock/types"),
  ]);

  root.innerHTML = `
    <h1 class="page-title">Sales</h1>
    <p class="page-sub">Credit is always computed as Total &minus; Received — never entered directly.</p>
    <div class="card">
      <h3>Record a Sale</h3>
      <form id="sale-form">
        <div class="field"><label>Date</label><input type="date" name="sale_date" value="${todayStr()}" required></div>
        <div class="field grow"><label>Customer</label>
          <select name="customer_id" required>${customers.map(c => `<option value="${c.id}">${c.name}</option>`).join("")}</select>
        </div>
        <div class="field grow"><label>Stock Type</label>
          <select name="stock_type_id" required>${stockTypes.map(s => `<option value="${s.id}">${s.name}</option>`).join("")}</select>
        </div>
        <div class="field"><label>Quantity</label><input type="number" step="0.01" name="quantity" required></div>
        <div class="field"><label>Rate / unit</label><input type="number" step="0.01" name="rate" required></div>
        <div class="field"><label>Cash Received</label><input type="number" step="0.01" name="cash_received" value="0"></div>
        <div class="field"><label>Bank Received</label><input type="number" step="0.01" name="bank_received" value="0"></div>
        <div class="field grow"><label>Notes</label><input type="text" name="notes"></div>
        <button type="submit">Record Sale</button>
      </form>
      ${customers.length === 0 ? `<p class="hint">Add a customer first, in the Customers tab.</p>` : ""}
      ${stockTypes.length === 0 ? `<p class="hint">Add a stock type first, in the Stock tab.</p>` : ""}
    </div>`;

  bindForm(document.getElementById("sale-form"), root, async (e) => {
    const fd = new FormData(e.target);
    const payload = {
      sale_date: fd.get("sale_date"),
      customer_id: Number(fd.get("customer_id")),
      stock_type_id: Number(fd.get("stock_type_id")),
      quantity: Number(fd.get("quantity")),
      rate: Number(fd.get("rate")),
      cash_received: Number(fd.get("cash_received") || 0),
      bank_received: Number(fd.get("bank_received") || 0),
      notes: fd.get("notes") || null,
    };
    const sale = await api("/sales", { method: "POST", body: JSON.stringify(payload) });
    toast("ok", `Sale recorded — total ${fmtMoney(sale.total_amount)}, credit ${fmtMoney(sale.credit_amount)}.`);
    e.target.reset();
    document.querySelector('[name=sale_date]').value = todayStr();
    await notifyDataChanged(["stock", "sales", "cashbank", "credit"]);
  });
}

// ---------------------------------------------------------------- EXPENSES
async function renderExpenses(root) {
  const categories = await api("/expenses/categories");

  root.innerHTML = `
    <h1 class="page-title">Expenses</h1>
    <div class="card">
      <h3>Add Expense Category</h3>
      <form id="cat-form">
        <div class="field grow"><label>Category name</label><input type="text" name="name" required placeholder="e.g. Vehicle Rent"></div>
        <button type="submit" class="secondary">Add Category</button>
      </form>
    </div>
    <div class="card">
      <h3>Record an Expense</h3>
      <form id="expense-form">
        <div class="field"><label>Date</label><input type="date" name="expense_date" value="${todayStr()}" required></div>
        <div class="field grow"><label>Category</label>
          <select name="category_id" required>${categories.map(c => `<option value="${c.id}">${c.name}</option>`).join("")}</select>
        </div>
        <div class="field"><label>Amount</label><input type="number" step="0.01" name="amount" required></div>
        <div class="field"><label>Payment</label>
          <select name="payment_method"><option value="CASH">Cash</option><option value="BANK">Bank</option></select>
        </div>
        <div class="field grow"><label>Description</label><input type="text" name="description"></div>
        <button type="submit">Record Expense</button>
      </form>
      ${categories.length === 0 ? `<p class="hint">Add a category above first.</p>` : ""}
    </div>`;

  bindForm(document.getElementById("cat-form"), root, async (e) => {
    const fd = new FormData(e.target);
    await api("/expenses/categories", { method: "POST", body: JSON.stringify({ name: fd.get("name") }) });
    toast("ok", "Category added.");
    navigate("expenses");
  });

  bindForm(document.getElementById("expense-form"), root, async (e) => {
    const fd = new FormData(e.target);
    const payload = {
      expense_date: fd.get("expense_date"),
      category_id: Number(fd.get("category_id")),
      amount: Number(fd.get("amount")),
      payment_method: fd.get("payment_method"),
      description: fd.get("description") || null,
    };
    const exp = await api("/expenses", { method: "POST", body: JSON.stringify(payload) });
    toast("ok", `Recorded ${fmtMoney(exp.amount)} expense.`);
    e.target.reset();
    document.querySelector('[name=expense_date]').value = todayStr();
    await notifyDataChanged(["expenses", "cashbank"]);
  });
}

// ---------------------------------------------------------------- CUSTOMERS / CREDIT
async function renderCustomers(root) {
  const [customers, outstanding] = await Promise.all([
    api("/customers"), api("/customers/credit/outstanding"),
  ]);
  const balanceByCust = Object.fromEntries(outstanding.map(o => [o.customer_id, o.outstanding]));

  root.innerHTML = `
    <h1 class="page-title">Customers &amp; Credit</h1>
    <div class="two-col">
      <div class="card">
        <h3>Add Customer</h3>
        <form id="cust-form">
          <div class="field grow"><label>Name</label><input type="text" name="name" required></div>
          <div class="field grow"><label>Disambiguator (optional)</label><input type="text" name="disambiguator" placeholder="e.g. Market Street"></div>
          <div class="field"><label>Phone</label><input type="text" name="phone"></div>
          <div class="field"><label>Opening balance</label><input type="number" step="0.01" name="opening_balance" value="0"></div>
          <button type="submit">Add Customer</button>
        </form>
      </div>
      <div class="card">
        <h3>Record Credit Payment</h3>
        <form id="payment-form">
          <div class="field grow"><label>Customer</label>
            <select name="customer_id" required>${customers.map(c => `<option value="${c.id}">${c.name} (owes ${fmtMoney(balanceByCust[c.id] || 0)})</option>`).join("")}</select>
          </div>
          <div class="field"><label>Amount Paid</label><input type="number" step="0.01" name="amount" required></div>
          <div class="field"><label>Date</label><input type="date" name="payment_date" value="${todayStr()}" required></div>
          <div class="field"><label>Method</label>
            <select name="payment_method"><option value="CASH">Cash</option><option value="BANK">Bank</option></select>
          </div>
          <button type="submit">Record Payment</button>
        </form>
      </div>
    </div>
    <div class="card">
      <h3>Customer-wise Outstanding Credit</h3>
      <table>
        <tr><th>Customer</th><th>Phone</th><th class="num">Outstanding</th></tr>
        ${customers.map(c => `
          <tr>
            <td>${c.name}${c.disambiguator ? ` <span class="hint">(${c.disambiguator})</span>` : ""}</td>
            <td>${c.phone || "\u2014"}</td>
            <td class="num mono">${fmtMoney(balanceByCust[c.id] || 0)}
              ${balanceByCust[c.id] > 0 ? `<span class="pill credit">DUE</span>` : `<span class="pill paid">CLEAR</span>`}
            </td>
          </tr>`).join("") || `<tr><td colspan="3" class="hint">No customers yet.</td></tr>`}
      </table>
    </div>`;

  bindForm(document.getElementById("cust-form"), root, async (e) => {
    const fd = new FormData(e.target);
    const payload = {
      name: fd.get("name"),
      disambiguator: fd.get("disambiguator") || null,
      phone: fd.get("phone") || null,
      opening_balance: Number(fd.get("opening_balance") || 0),
    };
    await api("/customers", { method: "POST", body: JSON.stringify(payload) });
    toast("ok", `Customer "${payload.name}" added.`);
    navigate("customers");
  });

  bindForm(document.getElementById("payment-form"), root, async (e) => {
    const fd = new FormData(e.target);
    const customerId = Number(fd.get("customer_id"));
    const payload = {
      payment_date: fd.get("payment_date"),
      customer_id: customerId,
      amount: Number(fd.get("amount")),
      payment_method: fd.get("payment_method"),
    };
    await api(`/customers/${customerId}/payments`, { method: "POST", body: JSON.stringify(payload) });
    toast("ok", `Payment of ${fmtMoney(payload.amount)} recorded.`);
    await notifyDataChanged(["credit", "cashbank"]);
    navigate("customers");
  });
}

// ---------------------------------------------------------------- STOCK
async function renderStock(root) {
  const [snapshot, stockTypes] = await Promise.all([
    api("/stock/snapshot"), api("/stock/types"),
  ]);

  root.innerHTML = `
    <h1 class="page-title">Stock</h1>
    <div class="two-col">
      <div class="card">
        <h3>Add Stock Type</h3>
        <form id="type-form">
          <div class="field grow"><label>Name</label><input type="text" name="name" required placeholder="e.g. Mayur, MK, MR"></div>
          <div class="field"><label>Unit</label><input type="text" name="unit" value="bag"></div>
          <button type="submit">Add</button>
        </form>
      </div>
      <div class="card">
        <h3>Record Purchase</h3>
        <form id="purchase-form">
          <div class="field grow"><label>Stock Type</label>
            <select name="stock_type_id" required>${stockTypes.map(s => `<option value="${s.id}">${s.name}</option>`).join("")}</select>
          </div>
          <div class="field"><label>Quantity</label><input type="number" step="0.01" name="quantity" required></div>
          <div class="field"><label>Rate</label><input type="number" step="0.01" name="rate" required></div>
          <div class="field"><label>Date</label><input type="date" name="purchase_date" value="${todayStr()}" required></div>
          <button type="submit">Record Purchase</button>
        </form>
      </div>
    </div>
    <div class="card">
      <h3>Record Stock Adjustment (used, recount, damage, etc.)</h3>
      <p class="hint" style="margin:-6px 0 12px">Positive = stock added (e.g. found extra on recount). Negative = stock removed (e.g. "used 400 bags today" → −400).</p>
      <form id="adj-form">
        <div class="field grow"><label>Stock Type</label>
          <select name="stock_type_id" required>${stockTypes.map(s => `<option value="${s.id}">${s.name}</option>`).join("")}</select>
        </div>
        <div class="field"><label>Quantity Δ (+/-)</label><input type="number" step="0.01" name="quantity_delta" required placeholder="e.g. -400"></div>
        <div class="field grow"><label>Reason</label><input type="text" name="reason" required placeholder="e.g. used today"></div>
        <div class="field"><label>Date</label><input type="date" name="adjustment_date" value="${todayStr()}" required></div>
        <button type="submit" class="secondary">Adjust</button>
      </form>
    </div>
    <div class="card">
      <h3>Current Stock</h3>
      <table id="stock-table">
        <tr><th>Type</th><th class="num">Quantity</th><th>Last Physical Count</th></tr>
        ${snapshot.map(s => `
          <tr data-stock-id="${s.stock_type_id}">
            <td>${s.name}</td>
            <td class="num mono">${fmtQty(s.quantity)} ${s.unit}(s)</td>
            <td>${s.last_physical_count_date ? s.last_physical_count_date : `<span class="pill credit">never counted</span>`}</td>
          </tr>`).join("") || `<tr><td colspan="3" class="hint">No stock types yet.</td></tr>`}
      </table>
    </div>`;

  bindForm(document.getElementById("type-form"), root, async (e) => {
    const fd = new FormData(e.target);
    await api("/stock/types", { method: "POST", body: JSON.stringify({ name: fd.get("name"), unit: fd.get("unit") || "bag" }) });
    toast("ok", "Stock type added.");
    navigate("stock");
  });

  bindForm(document.getElementById("purchase-form"), root, async (e) => {
    const fd = new FormData(e.target);
    const payload = {
      purchase_date: fd.get("purchase_date"),
      stock_type_id: Number(fd.get("stock_type_id")),
      quantity: Number(fd.get("quantity")),
      rate: Number(fd.get("rate")),
    };
    await api("/stock/purchases", { method: "POST", body: JSON.stringify(payload) });
    toast("ok", `Purchase of ${payload.quantity} recorded.`);
    await notifyDataChanged(["stock", "cashbank"]);
    navigate("stock");
  });

  bindForm(document.getElementById("adj-form"), root, async (e) => {
    const fd = new FormData(e.target);
    const payload = {
      adjustment_date: fd.get("adjustment_date"),
      stock_type_id: Number(fd.get("stock_type_id")),
      quantity_delta: Number(fd.get("quantity_delta")),
      reason: fd.get("reason"),
    };
    await api("/stock/adjustments", { method: "POST", body: JSON.stringify(payload) });
    toast("ok", `Stock adjusted by ${payload.quantity_delta > 0 ? "+" : ""}${payload.quantity_delta}.`);
    await notifyDataChanged(["stock"]);
    navigate("stock");
  });
}

// ---------------------------------------------------------------- CASH/BANK
async function renderCashBank(root) {
  const balances = await api("/cashbank/balances");

  root.innerHTML = `
    <h1 class="page-title">Cash &amp; Bank</h1>
    <div class="stat-grid">
      <div class="stat good"><div class="stat-label">Cash in Hand</div><div class="stat-value">${fmtMoney(balances.cash)}</div></div>
      <div class="stat good"><div class="stat-label">Bank Balance</div><div class="stat-value">${fmtMoney(balances.bank)}</div></div>
    </div>
    <div class="two-col">
      <div class="card">
        <h3>Manual Cash Adjustment</h3>
        <form id="cash-form">
          <div class="field"><label>Amount</label><input type="number" step="0.01" name="amount" required></div>
          <div class="field"><label>Direction</label>
            <select name="direction"><option value="in">Cash In</option><option value="out">Cash Out</option></select>
          </div>
          <div class="field grow"><label>Reason</label><input type="text" name="reason" required></div>
          <div class="field"><label>Date</label><input type="date" name="date" value="${todayStr()}" required></div>
          <button type="submit" class="secondary">Apply</button>
        </form>
      </div>
      <div class="card">
        <h3>Transfer Cash \u2192 Bank</h3>
        <form id="transfer-form">
          <div class="field"><label>Amount</label><input type="number" step="0.01" name="amount" required></div>
          <div class="field grow"><label>Reason</label><input type="text" name="reason" value="Cash deposited to bank"></div>
          <div class="field"><label>Date</label><input type="date" name="date" value="${todayStr()}" required></div>
          <button type="submit" class="secondary">Transfer</button>
        </form>
      </div>
    </div>`;

  bindForm(document.getElementById("cash-form"), root, async (e) => {
    const fd = new FormData(e.target);
    const dir = fd.get("direction");
    const payload = { date: fd.get("date"), amount: Number(fd.get("amount")), reason: fd.get("reason") };
    await api(`/cashbank/cash/${dir}`, { method: "POST", body: JSON.stringify(payload) });
    toast("ok", "Cash adjustment applied.");
    await notifyDataChanged(["cashbank"]);
    navigate("cashbank");
  });

  bindForm(document.getElementById("transfer-form"), root, async (e) => {
    const fd = new FormData(e.target);
    const payload = { date: fd.get("date"), amount: Number(fd.get("amount")), reason: fd.get("reason") };
    await api("/cashbank/transfer-to-bank", { method: "POST", body: JSON.stringify(payload) });
    toast("ok", "Transfer complete.");
    await notifyDataChanged(["cashbank"]);
    navigate("cashbank");
  });
}

// ---------------------------------------------------------------- REPORTS
async function renderReports(root) {
  root.innerHTML = `
    <h1 class="page-title">Reports</h1>
    <div class="card">
      <form id="report-form">
        <div class="field"><label>Date</label><input type="date" name="report_date" value="${todayStr()}" required></div>
        <button type="submit">Generate Daily Report</button>
      </form>
    </div>
    <div id="report-output"></div>`;

  bindForm(document.getElementById("report-form"), root, async (e) => {
    const fd = new FormData(e.target);
    const date = fd.get("report_date");
    const text = await fetch(`/reports/daily/text?report_date=${date}`).then(r => r.text());
    document.getElementById("report-output").innerHTML = `<div class="card"><pre class="report">${text}</pre></div>`;
  });
}

// ---------------------------------------------------------------- EXCEL
async function renderExcel(root) {
  root.innerHTML = `
    <h1 class="page-title">Excel</h1>
    <p class="page-sub">Excel is a reporting/import layer only — it never overwrites the database directly.</p>
    <div class="msg info">Excel import/export hasn't been split into its own service yet in this deployment — the buttons below will return "not implemented" for now.</div>
    <div class="card">
      <h3>Export</h3>
      <form id="export-form">
        <div class="field"><label>From</label><input type="date" name="start_date" value="${todayStr()}" required></div>
        <div class="field"><label>To</label><input type="date" name="end_date" value="${todayStr()}" required></div>
        <button type="submit">Download .xlsx</button>
      </form>
    </div>
    <div class="card">
      <h3>Import Sales</h3>
      <p class="hint">Upload a Sales sheet (same columns as the export). Step 1 previews and validates — nothing is written until you confirm.</p>
      <form id="import-form">
        <div class="field grow"><label>File</label><input type="file" name="file" accept=".xlsx" required></div>
        <button type="submit" class="secondary">Preview Import</button>
      </form>
      <div id="import-preview"></div>
    </div>`;

  document.getElementById("export-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    const url = `/excel/export?start_date=${fd.get("start_date")}&end_date=${fd.get("end_date")}`;
    window.open(url, "_blank");
  });

  document.getElementById("import-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const fileInput = e.target.querySelector('[name=file]');
    const file = fileInput.files[0];
    if (!file) return;
    const fd = new FormData();
    fd.append("file", file);
    const previewBox = document.getElementById("import-preview");
    previewBox.innerHTML = `<p class="hint">Validating...</p>`;
    try {
      const res = await fetch("/excel/import/sales/preview", { method: "POST", body: fd });
      const summary = await res.json();
      if (!res.ok) throw new Error(summary.detail || "Preview failed");

      previewBox.innerHTML = `
        <div class="msg ${summary.is_clean ? "ok" : "error"}">
          ${summary.valid_row_count} valid row(s), ${summary.error_count} error(s).
        </div>
        ${summary.errors.length ? `<ul>${summary.errors.map(e => `<li>${e}</li>`).join("")}</ul>` : ""}
        ${summary.is_clean ? `<button id="confirm-import">Confirm &amp; Import ${summary.valid_row_count} Row(s)</button>` : ""}`;

      if (summary.is_clean) {
        document.getElementById("confirm-import").addEventListener("click", async () => {
          const fd2 = new FormData();
          fd2.append("file", file);
          try {
            const res2 = await fetch("/excel/import/sales/commit", { method: "POST", body: fd2 });
            const result = await res2.json();
            if (!res2.ok) throw new Error(result.detail || "Import failed");
            toast("ok", `Imported ${result.imported_count} sale(s).`);
            previewBox.innerHTML = "";
            await notifyDataChanged(["stock", "sales", "cashbank", "credit"]);
          } catch (err) { toast("error", err.message); }
        });
      }
    } catch (err) {
      previewBox.innerHTML = `<div class="msg error">${err.message}</div>`;
    }
  });
}

// ---------------------------------------------------------------- ASSISTANT
const SUGGESTIONS = [
  "Used 400 bags of Mayur today",
  "Sold 5 bags of Mayur to Ramesh for 3000, he paid cash",
  "How much stock do I have?",
  "How much does Ramesh owe me?",
  "What's 12% of 45000?",
  "At this rate, how much profit will I make this month?",
  "Give me today's report",
];

async function renderAssistant(root) {
  root.innerHTML = `
    <h1 class="page-title">Assistant</h1>
    <p class="page-sub">Talks to a local Ollama model. It can record and correct real data (every action goes through the same validated services as the forms, and updates the live figures on the right the moment it's done) — and it can also just answer questions: quick calculations, and business estimates grounded in your actual recent numbers.</p>
    <div class="assistant-layout">
      <div class="card">
        <h3>Chat <span id="assistant-status" class="assistant-status"><span class="dot"></span><span class="label">Checking\u2026</span></span></h3>
        <div class="suggestion-row" id="suggestion-row">
          ${SUGGESTIONS.map(s => `<span class="chip" data-text="${s.replace(/"/g, '&quot;')}">${s}</span>`).join("")}
        </div>
        <div id="chat-log"></div>
        <form id="chat-form">
          <input type="text" id="chat-input" placeholder="e.g. Used 400 bags of Mayur today" autocomplete="off">
          <button type="submit">Send</button>
        </form>
      </div>
      <div class="card snapshot-card">
        <h3>Live Snapshot</h3>
        <div class="snapshot-row"><span>Cash</span><span class="val" id="snap-cash">\u2014</span></div>
        <div class="snapshot-row"><span>Bank</span><span class="val" id="snap-bank">\u2014</span></div>
        <div class="snapshot-row"><span>Total stock</span><span class="val" id="snap-stock">\u2014</span></div>
        <div class="snapshot-row"><span>Credit outstanding</span><span class="val" id="snap-credit">\u2014</span></div>
        <p class="hint">Updates automatically whenever the assistant records something.</p>
      </div>
    </div>`;

  const log = document.getElementById("chat-log");
  checkAssistantStatus();
  refreshSnapshot();

  document.querySelectorAll("#suggestion-row .chip").forEach((chip) => {
    chip.addEventListener("click", () => {
      document.getElementById("chat-input").value = chip.dataset.text;
      document.getElementById("chat-form").dispatchEvent(new Event("submit", { cancelable: true }));
    });
  });

  function addUserBubble(text) {
    log.appendChild(el(`
      <div class="chat-row user">
        <div class="chat-avatar">You</div>
        <div class="chat-bubble-wrap">
          <div class="chat-bubble">${escapeHTML(text)}</div>
          <span class="chat-time">${timeStr()}</span>
        </div>
      </div>`));
    log.scrollTop = log.scrollHeight;
  }

  function addTypingBubble() {
    const row = el(`
      <div class="chat-row assistant" id="typing-row">
        <div class="chat-avatar">AI</div>
        <div class="chat-bubble-wrap">
          <div class="chat-bubble"><span class="typing-dots"><span></span><span></span><span></span></span></div>
        </div>
      </div>`);
    log.appendChild(row);
    log.scrollTop = log.scrollHeight;
    return row;
  }

  function addAssistantBubble(text, { cls = "", affected = [] } = {}) {
    const chip = affected.length
      ? `<span class="chat-updated-chip">\u2713 Updated: ${affected.join(", ")}</span>`
      : "";
    log.appendChild(el(`
      <div class="chat-row assistant">
        <div class="chat-avatar">AI</div>
        <div class="chat-bubble-wrap">
          <div class="chat-bubble ${cls}">${escapeHTML(text)}</div>
          ${chip}
          <span class="chat-time">${timeStr()}</span>
        </div>
      </div>`));
    log.scrollTop = log.scrollHeight;
  }

  document.getElementById("chat-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const input = document.getElementById("chat-input");
    const message = input.value.trim();
    if (!message) return;
    addUserBubble(message);
    input.value = "";
    const typingRow = addTypingBubble();

    try {
      const res = await api("/assistant/chat", { method: "POST", body: JSON.stringify({ message }) });
      typingRow.remove();
      await handleAssistantResponse(res, log, addAssistantBubble);
    } catch (err) {
      typingRow.remove();
      addAssistantBubble(`Error: ${err.message}`, { cls: "error-bubble" });
      toast("error", err.message);
    }
  });

  async function handleAssistantResponse(res, log, addBubble) {
    if (res.status === "needs_confirmation") {
      const bubble = el(`
        <div class="chat-row assistant">
          <div class="chat-avatar">AI</div>
          <div class="chat-bubble-wrap">
            <div class="chat-bubble confirm">${escapeHTML(res.message)}
              <div class="chat-actions">
                <button id="confirm-yes">Confirm</button>
                <button id="confirm-no" class="secondary">Cancel</button>
              </div>
            </div>
            <span class="chat-time">${timeStr()}</span>
          </div>
        </div>`);
      log.appendChild(bubble);
      log.scrollTop = log.scrollHeight;

      bubble.querySelector("#confirm-yes").addEventListener("click", async () => {
        bubble.querySelectorAll("button").forEach(b => (b.disabled = true));
        try {
          const res2 = await api("/assistant/chat", {
            method: "POST",
            body: JSON.stringify({ message: "", intent: res.intent, confirmed: true }),
          });
          addBubble(res2.message, { affected: (res2.data && res2.data.affected) || [] });
          if (res2.status === "ok") {
            toast("ok", "Change confirmed and applied.");
            await notifyDataChanged((res2.data && res2.data.affected) || []);
            refreshSnapshot();
          }
        } catch (err) {
          addBubble(`Error: ${err.message}`, { cls: "error-bubble" });
          toast("error", err.message);
        }
      });
      bubble.querySelector("#confirm-no").addEventListener("click", () => {
        bubble.querySelectorAll("button").forEach(b => (b.disabled = true));
        addBubble("Cancelled - nothing was changed.");
      });
      return;
    }

    const affected = (res.data && res.data.affected) || [];
    addBubble(res.message, { cls: res.status === "error" ? "error-bubble" : "", affected });
    if (res.status === "ok" && affected.length) {
      toast("ok", `Recorded. Live figures updated: ${affected.join(", ")}.`);
      await notifyDataChanged(affected);
      refreshSnapshot();
    } else if (res.status === "needs_clarification") {
      toast("info", "Needs a bit more detail — see the chat.");
    } else if (res.status === "error") {
      toast("error", res.message);
    }
  }
}

async function refreshSnapshot() {
  try {
    const [balances, snapshot, outstanding] = await Promise.all([
      api("/cashbank/balances"), api("/stock/snapshot"), api("/customers/credit/outstanding"),
    ]);
    const totalStock = snapshot.reduce((s, r) => s + Number(r.quantity || 0), 0);
    const totalCredit = outstanding.reduce((s, r) => s + Number(r.outstanding || 0), 0);
    flashSnapshotValue("snap-cash", fmtMoney(balances.cash));
    flashSnapshotValue("snap-bank", fmtMoney(balances.bank));
    flashSnapshotValue("snap-stock", fmtQty(totalStock) + " bag(s)");
    flashSnapshotValue("snap-credit", fmtMoney(totalCredit));
  } catch (err) { /* snapshot is best-effort UI sugar - ignore failures */ }
}
function flashSnapshotValue(id, text) {
  const node = document.getElementById(id);
  if (!node) return;
  const changed = node.textContent !== text;
  node.textContent = text;
  if (changed) {
    node.classList.remove("flash");
    void node.offsetWidth;
    node.classList.add("flash");
  }
}

async function checkAssistantStatus() {
  const statusEl = document.getElementById("assistant-status");
  const badge = document.getElementById("assistant-badge");
  if (!statusEl) return;
  try {
    await fetch("/assistant/chat", { method: "OPTIONS" }).catch(() => {});
    // A lightweight reachability probe: try /assistant health via a HEAD-like
    // GET is not exposed publicly through the gateway (only /assistant/chat
    // is proxied), so we infer readiness optimistically and let the first
    // real chat call surface a clear error if Ollama itself is unreachable.
    statusEl.classList.add("online");
    statusEl.querySelector(".label").textContent = "Ready";
    if (badge) badge.hidden = false;
  } catch (err) {
    statusEl.classList.add("offline");
    statusEl.querySelector(".label").textContent = "Unavailable";
    if (badge) badge.hidden = true;
  }
}

function escapeHTML(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}
