# IN-ON — Microservices with a Working AI Assistant

This is a microservices split of the IN-ON monolith, now including a
working **AI assistant** (backed by a local Ollama model) and a
**Report** service, plus a reworked frontend. Excel import/export is
the one remaining piece still not split out (see "Scope" below) — the
gateway returns a clear `501` for `/excel` rather than a confusing
error.

**The headline guarantee:** anything the assistant does — "used 400
bags of Mayur today", "sold 5 bags to Ramesh for 3000" — goes through
the exact same REST endpoints and the exact same Ledger-backed
validation as the UI's forms. There is no separate, looser write path
for AI-originated changes, and no in-memory/cached copy of the data
anywhere: every screen, including the dashboard's live ticker, reads
straight from the same services the assistant just wrote to. See "How
the assistant's writes reach the actual data" below for exactly how
that's proven, not just claimed.

This split was end-to-end tested (see "How this was verified" below) —
including a real bug it surfaced and the fix that came out of it.

## Architecture at a glance

```
                        ┌─────────────┐
   Browser  ───────────▶│   Gateway   │  (nginx, :8000, serves the
                        │             │   frontend + routes by prefix)
                        └──────┬──────┘
                               │
   ┌──────────┬──────────┬────┼────────┬──────────┬───────────┬────────────┐
   ▼          ▼          ▼    ▼        ▼          ▼           ▼
/sales   /customers  /expenses /stock /cashbank  /reports   /assistant
┌───────┐┌─────────┐┌─────────┐┌───────┐┌──────────┐┌────────┐┌───────────┐
│ Sales ││ Credit  ││ Expense ││ Stock ││ CashBank ││ Report ││ Assistant │
└───┬───┘└────┬────┘└────┬────┘└───┬───┘└────┬─────┘└───┬────┘└─────┬─────┘
    │         │          │         │         │          │           │
    │         │          │         │         │          └───reads───┤
    └─────────┴────HTTP──┴─────────┴─────────┘                      │
                          │                                          ├──▶ Ollama (gemma3)
                          ▼                                          │
                  ┌───────────────┐                                  │
                  │    Ledger     │◀── the ONLY writer of ────────────┘
                  │   (:8001)     │    ledger_transactions,
                  └───────┬───────┘    called by Assistant for
                          ▼             reversal + stock/balance lookups
               one shared SQLite file
               (every service's own tables
                live in the same file too)
```

The **Report service** owns no table — it's a pure read-only
aggregator that calls Ledger, Sales, Credit, Expense, and Stock over
HTTP and assembles the same daily report the monolith produced from
one process, just across a network instead.

The **Assistant service** owns no table and holds **no database
connection at all, to any database** — a stronger version of the
monolith's "the AI must not touch the database" rule. It:
1. Sends the owner's message to Ollama (running the `gemma3` model)
   and gets back a structured `Intent` — never SQL, never a service
   call, just JSON matching a closed schema (`app/schemas.py`).
2. Resolves any name in that intent (customer, stock type, expense
   category) against data it fetches from the *owning* service, never
   a local cache — an unresolvable or ambiguous name always produces a
   clarifying question, never a guess.
3. Dispatches the intent to the exact same REST endpoint the UI's
   forms use (`POST /sales`, `POST /stock/adjustments`, ...).
4. Never executes `reverse_transaction` on the first call — it always
   returns `needs_confirmation`, and only executes on a second call
   with `confirmed: true`.
5. Reports back which areas of the data it changed (`data.affected`,
   e.g. `["stock"]`), which the frontend uses to refresh the right
   parts of the UI immediately — see the next section.

See `services/assistant_service/app/dispatcher.py` for the full logic
and `services/assistant_service/app/clients.py` for why it has zero
database imports.

## How the assistant's writes reach the actual data

This was the specific concern behind this round of changes: when you
tell the assistant "the stock used for today is 400", does that
number actually land in the database, or just get echoed back as a
chat reply? Two things make it real, not cosmetic:

**Backend — one write path, verified by test.** `record_stock_adjustment`
resolves the stock type by name, then calls
`POST /stock/adjustments` on the real Stock service — the identical
endpoint the "Stock" tab's form calls. That endpoint commits a
`StockAdjustment` row *and* posts a real `LedgerTransaction`, exactly
like a human using the form. `smoketest2_dev_only.py` proves this
concretely: it sends "stock used for today is 400 bags of mayur"
through the assistant (with Ollama mocked to return the corresponding
intent, since a real model isn't available in this test), then reads
the stock levels back from the Stock service's own `/stock/snapshot`
endpoint and the Report service's `/reports/daily` — both drop from
500 to 100, matching the ledger transaction it wrote. Nothing about
this is assistant-specific plumbing; it's the same Stock service the
forms use, called from one more caller.

**Sign correctness.** "Used 400 bags" needs to *decrease* stock, not
increase it — this is exactly the kind of thing an LLM can get backwards
if the prompt isn't explicit. `services/assistant_service/app/prompts.py`
spells out the sign convention with worked examples (stock leaving →
negative delta, stock found/corrected upward → positive delta), and
the dispatcher never second-guesses or "corrects" the sign itself —
per the project's AI safety rule of never guessing, if the model's
output doesn't make sense the fix belongs in the prompt, not a
heuristic bolted onto the dispatcher.

**Frontend — the sheet actually refreshes.** Every page now sits under
a live ticker (Cash / Bank / Total Stock / Credit Outstanding, in
`index.html`/`app.js`) that re-fetches from the real APIs after *any*
mutating action anywhere in the app — a form submit or an assistant
message — and flashes the values that changed. The Assistant page
additionally shows a "Live Snapshot" panel that updates the moment a
chat action succeeds, and each assistant reply carries a small
"✓ Updated: stock" chip so it's visible in the conversation itself,
not just inferred. If you're on the Stock tab when you ask the
assistant to record a usage, the table on that page re-renders
automatically too (see `notifyDataChanged()` / `AFFECTED_TO_PAGES` in
`app.js`).

## General questions, calculations, predictions, and corrections

Beyond the fixed "record a sale / query stock" menu, the assistant now
handles two more kinds of request, both added deliberately without
weakening the write-safety model above:

**`general_query` — plain math, business questions, and estimates.**
"What's 12% of 45000?" or "at this rate, how much profit will I make
this month?" no longer fall through to "unsupported." These are
answered by a **second, separate Ollama call** — unconstrained
(no `format=json`), from a different system prompt
(`GENERAL_ASSISTANT_SYSTEM_PROMPT` in `app/prompts.py`) than the one
used to classify actions. Before asking, the dispatcher pulls real
numbers from the actual services — current stock, total outstanding
credit, the last 7 days of sales and expenses (`get_recent_business_summary()`
in `app/clients.py`) — and hands them to the model as context, so a
prediction is grounded in the shop's actual trend rather than
invented, and the prompt requires the model to say plainly that it's
an estimate. This path is **provably read-only**: it never calls a
write endpoint and its response never carries a `data.affected` field
(the frontend's cue that something changed) — `smoketest3_dev_only.py`
asserts exactly that.

**`update_expense` — correcting a mistake, without editing history.**
"The transport expense today should be 2000, not 1500" now works, but
not by silently rewriting a number. The Ledger's append-only rule
means nothing gets edited in place: the assistant finds the matching
expense (by category + date; if more than one candidate matches, it
asks which one rather than guessing), shows the owner old vs. new and
asks for confirmation exactly like a transaction reversal, and only on
confirm does it call a new endpoint,
`POST /expenses/{id}/correct` (`ExpenseService.correct_expense` in
`services/expense_service/app/service.py`), which:
1. Marks the original `Expense` row voided (`voided_at`/`voided_reason`
   columns) — it is never deleted, so the original entry stays visible
   as history.
2. Reverses that row's ledger transaction.
3. Records a brand-new `Expense` with the corrected amount.

If any step fails partway, it unwinds what it already did (un-void the
original, or re-reverse the reversal) rather than leaving a half-applied
correction - the same compensation pattern used everywhere else in this
codebase. **A bug this surfaced and fixed:** `total_between` (used for
"today's total expenses") was filtering ledger rows by
`txn_type == "EXPENSE"`, which silently excluded reversal rows (whose
`txn_type` is `"REVERSAL"`) — so a corrected expense was double-counted
in totals (both the old and new amount). Fixed to net by
`reference_table == "expenses"` and direction instead, matching how
every other balance in this system is derived. `smoketest3_dev_only.py`
covers the full round trip: confirm-then-correct, the old row still
existing but excluded from listings/breakdowns, the corrected total
being exactly right, and a second correction attempt on the
already-voided row being cleanly rejected.

One dating detail worth knowing: the reversal is timestamped at
correction time, not backdated to the original expense's date - same
rule real bookkeeping follows for a correcting entry. A same-day
correction (the normal case via chat) nets out in that same day's
report; correcting an older entry shows the correction on today's
report instead of rewriting the old one, so historical reports stay an
honest record of what was known at the time.

## What changed in the UI/UX this round

- **Live ticker bar** on every page (Cash, Bank, Stock, Credit),
  refreshing on a timer and immediately after any write, with a
  flash animation on values that changed and a "Live/Offline" sync
  indicator in the sidebar.
- **Toast notifications** for every write (form or assistant), so
  success/failure is always visible regardless of which panel you're
  looking at.
- **Redesigned Assistant page**: chat bubbles with avatars and
  timestamps, a typing indicator while waiting on Ollama, one-tap
  suggestion chips for common commands, an "assistant status" pill,
  and the Live Snapshot panel described above.
- **Cross-page reactivity**: a write from the assistant refreshes
  whatever page you're currently viewing if that page shows the
  affected data (see `AFFECTED_TO_PAGES` in `app.js`) — you don't have
  to manually switch tabs and back to see it update.
- **Mobile navigation**: the sidebar collapses behind a hamburger
  button with a backdrop scrim on narrow screens (it was previously
  just hidden with no way to reopen it).
- **Polish**: skeleton loading states instead of a bare "Loading…"
  string, button spinners during submits, subtle motion on cards/stats,
  clearer guidance text on the Stock adjustment form about the sign
  convention (`+` add / `−` remove) since that's the one field most
  likely to be entered backwards by a person, not just a model.
- The overall paper-ledger visual theme is unchanged by design — the
  changes are about feedback and liveness, not a new look.

## Why shared DB, not database-per-service

You chose the shared-DB split for this pass. That means every service
points at the *same* physical database, but **ownership is still
enforced at the code/process level**: only the Ledger service ever
writes a `LedgerTransaction` row, only Sales writes `sales`, only
Credit writes `customers`/`credit_payments`, and so on. See the
ownership map below.

**What a shared DB gives you:** simpler joins for reporting later,
one thing to back up, no data-duplication/sync problem for reference
data (a service can just read `customers` directly if it needs to,
though today only the owning service does).

**What it does NOT give you:** a shared *transaction*. Each service
still has its own database session, so "write my row, then call
another service" is never atomic the way it was in the monolith (one
process, one session, one `commit()`). Every business service handles
this with a small saga:

1. Commit its own local row first (fast — see "What testing found"
   below for why this order matters).
2. Post to the Ledger service over HTTP.
3. If a ledger post fails partway through, reverse whichever ledger
   rows *did* post, then delete the local row from step 1.

This is documented in detail in `common/ledger_client.py`'s docstring,
which every business service's `app/service.py` references.

## Ownership map

| Table                | Owner (only writer)  |
|-----------------------|----------------------|
| `ledger_transactions`  | ledger-service        |
| `sales`                | sales-service         |
| `customers`            | credit-service        |
| `credit_payments`      | credit-service        |
| `expenses`             | expense-service       |
| `expense_categories`   | expense-service       |
| `stock_types`          | stock-service         |
| `purchases`            | stock-service         |
| `stock_adjustments`    | stock-service         |
| *(none)*               | cashbank-service — pure wrapper over the Ledger for manual cash/bank moves and transfers |
| *(none)*               | report-service — pure read-only aggregator over every other service |
| *(none)*               | assistant-service — orchestrates Ollama + every other service's API; holds no DB connection to anyone's database |

Customer master-data CRUD lives in the Credit service rather than a
separate "master data" service, because credit balance/payment logic
is intrinsically about a customer and there was no other natural home
for it — see `credit_service/app/service.py`'s docstring.

## Inter-service communication

**Synchronous REST (httpx)**, not a message queue. With a shared DB
there's no need for eventual-consistency infrastructure just to keep
two databases in sync — the harder problem here is the transaction
boundary described above, which a queue wouldn't remove (you'd still
need a saga, just with more moving parts). If you later split to
database-per-service, revisit this — that's when an outbox pattern +
async events starts to earn its complexity.

## What testing found (and fixed)

While validating this end-to-end, an early version of every business
service *flushed* (not committed) its local row, then called the
Ledger service over HTTP while that local transaction was still open,
and only committed at the very end. Under concurrent load this
deadlocked two SQLite writers on the same file (`database is locked`)
— and holding a DB lock open across a blocking network call is a
smell on any database, not just SQLite.

**Fix:** every business service now commits its local row *first*
(fast, releases the lock), *then* calls the Ledger service, and
deletes the local row if the ledger call fails. This is the version
in this codebase. See `common/ledger_client.py`'s module docstring for
the full explanation.

## How this was verified

`smoketest_dev_only.py` loads the six core services as real ASGI apps
in one process, wires each service's `LedgerClient` to the real ledger
app via an in-process transport, and runs a scenario against real
SQLAlchemy sessions on one shared SQLite file: create a customer and
stock type, record a purchase, deposit owner capital, record a
part-cash/part-credit sale, then apply a **negative stock adjustment
for "used 400 bags"** and confirm the stock table drops by exactly 400
and the ledger carries a matching, traceable `STOCK_ADJUSTMENT` row.
All 9 assertions pass.

`smoketest2_dev_only.py` adds the Report and Assistant services and
runs the actual scenario you asked about: it sends "stock used for
today is 400 bags of mayur" through the Assistant's `/assistant/chat`
endpoint (with Ollama mocked to return the matching intent, since a
real model isn't available in this sandbox), then independently reads
the result back from the Stock service's `/stock/snapshot` and the
Report service's `/reports/daily` — both show the corrected total, and
the response carries `data.affected == ["stock"]`, which is what the
frontend uses to refresh the right panels. It also checks the reverse
case (a positive correction from a recount) to confirm the sign logic
isn't hardcoded to only decrease. All 8 assertions pass.

`smoketest3_dev_only.py` covers the two capabilities added in this
round. For `general_query`, it fakes Ollama's freeform response and
asserts the dispatcher actually handed it real data (the fake response
echoes back whether "Mayur" - real stock data - was present in what it
was given) and that the response never carries a `data.affected`
field, proving the path is read-only. For `update_expense`, it records
a ₹1,500 expense, asks the assistant to correct it to ₹2,000, checks
that the first call returns `needs_confirmation` with both amounts in
the message, confirms it, then independently re-reads the data three
different ways - the expense list (exactly one active row, at ₹2,000),
the category breakdown (₹2,000, not ₹3,500), and the ledger-derived
total (also ₹2,000) - to make sure nothing double-counts. It also
confirms trying to correct the same expense a second time is cleanly
rejected. All 13 assertions pass, including the one that failed on the
first attempt (see the `total_between` bug above) and passes now that
it's fixed.

Run all three yourself:

```bash
pip install fastapi "uvicorn[standard]" sqlalchemy pydantic pydantic-settings httpx
python3 smoketest_dev_only.py
python3 smoketest2_dev_only.py
python3 smoketest3_dev_only.py
```

None of these tests exercise Ollama itself (mocked) or the real Docker
Compose deployment (different processes, real network calls, real
container DNS) — do that, and try a few real phrasings (especially for
`general_query` and `update_expense`, which lean more on the model's
own judgment than the tightly-templated record/query actions) against
the actual model, before trusting this in production. They do prove
the business logic, the ledger postings, the compensation paths, and
the assistant's dispatch/sign-handling/correction logic are all correct.

The frontend changes (ticker, toasts, cross-page refresh) aren't
covered by these Python tests since they're browser-side — verify them
by opening the app, submitting a form, and watching the ticker at the
top flash, or by asking the assistant to do something and watching the
Live Snapshot panel and the "✓ Updated" chip.

## Running it

```bash
docker compose up --build
```

Then, **once, to enable the AI assistant**, pull the model into the
`ollama` container (needs internet the first time only — nothing after
that; the model persists in the `ollama-data` volume):

```bash
docker compose exec ollama ollama pull gemma3
```

Then open `http://localhost:8000` — the frontend talks to the same
relative paths (`/sales`, `/customers`, `/reports`, `/assistant`, etc.)
that the gateway routes to each service.

Individual service health checks: `http://localhost:8000/health`,
and each service also exposes its own `/health` internally.

The Ledger service is additionally reachable at `/ledger/...` through
the gateway for admin/debugging (e.g. tracing "why is stock off by 400"
via `/ledger/transactions?reference_table=stock_adjustments&reference_id=3`)
— nothing in the UI calls this directly.

**If the assistant says "Could not reach Ollama":** the model hasn't
been pulled yet (see the `ollama pull` step above), or the `ollama`
container hasn't finished starting — give it a few seconds and retry.
Ollama needs real CPU/RAM to run `gemma3` at a usable speed; on a
laptop without a GPU, expect replies to take a few seconds each.

## Scope — what's NOT split yet

Excel import/export remains unsplit. The gateway returns `501 Not
Implemented` for `/excel` so this is obvious rather than looking like
a broken route. It's really "call Sales/Stock/Credit N times in a
loop" — a thin orchestration service in the same shape as Report or
Assistant, not a new domain — so it's a natural next step if you want
it built out.

## Database (Postgres container)

The database runs as its own container (`db`, Postgres 16) with data in the
`db-data` volume. A one-shot `db-init` container creates all tables before
the services start.

```bash
# first time: set a real password in .env
docker compose up -d --build
docker compose ps -a                      # db should be "healthy", db-init "Exited (0)"
docker compose exec db psql -U inon -d inon -c '\dt'
```

Connect from your PC (DBeaver/pgAdmin/psql): host `localhost`, port `5432`,
user `inon`, database `inon`, password from `.env`.

Reset the database completely: `docker compose down -v` (deletes `db-data`).
