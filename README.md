# MediTrack: appointment no-show reconciliation

A small web app for clinic staff to enter the day's appointments, mark each one **attended** or **no-show**
as the day goes on, and see which upcoming appointments are most likely to be missed. A machine-learning model
scores every appointment the moment it is saved and learns from the outcomes staff record.

Python 3.11+ · FastAPI · SQLite · scikit-learn · vanilla JavaScript (no build step)

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt

cp .env.example .env              # demo passwords; edit if you like (never commit .env)
python scripts/seed_demo.py       # optional: ~6 weeks of fake history so the dashboard has data
python main.py                    # or: python -m app, or uvicorn app.main:get_app --factory
```

Open <http://localhost:8000> and sign in with one of the accounts below.
(Without `.env`, the first start generates random passwords and prints them once to the server log.)

| User | Role | Can do |
|---|---|---|
| `admin` | admin | everything, including deleting appointments and retraining the model |
| `staff` | staff | enter appointments, reconcile outcomes, view dashboard, model info and export CSV |
| `auditor` | auditor | read-only: view appointments, dashboard and export |

Demo passwords in `.env.example` are `admin-demo-2026`, `staff-demo-2026`, `auditor-demo-2026`.

```bash
pytest                              # 128 backend tests (~40 s; trains a small model per app instance)
node --test tests/js/*.test.mjs     # 5 frontend parser tests
python scripts/benchmark_models.py  # reproduces the accuracy-vs-latency table below
```

## How it maps to the brief

| Requirement | Where |
|---|---|
| **Must** – staff enter appointments (patient name, time) | *Appointments* tab: single form and "paste a list" bulk entry; `app/schemas.py` validates everything |
| **Must** – ML model predicts no-shows from historical data | `app/ml/`: features, model, synthetic baseline; every saved appointment gets a risk score |
| **Should** – dashboard: no-shows, predicted no-shows, trends | *Dashboard* tab: KPIs, per-day bars vs model-expected line, rolling 7-day rate, next 7 days, breakdowns, prediction quality |
| **Should** – export analysis as CSV | *Export CSV* button / `GET /api/reports/no-show.csv` (per-appointment or daily summary) |
| **Must** – role-based access control | `app/security.py` + `require(permission)` dependency on every route; UI hides what a role cannot do |
| **Must** – architecture and accuracy/response-time trade-off documented | below |
| **Could** – dashboard caching | `app/cache.py`: TTL cache invalidated on every write |

## Architecture

```
 Browser (vanilla JS modules, SVG charts)
        │  JSON over HTTP, HttpOnly session cookie
        ▼
 FastAPI app (app/main.py: factory, error handlers, security headers)
   routers/      thin HTTP layer: parse, authorise, call a service, shape the response
   deps.py       current_user + require(permission): the single RBAC choke-point
   services/     appointments (create/score/reconcile) · dashboard (aggregation) · reports (CSV)
   ml/           features.py · synthetic.py · model.py (ModelService)
   cache.py      TTL cache with invalidation        security.py  scrypt, sessions, throttle, roles
   db.py         SQLite repositories (all SQL, all parameterised)
        ▼
 SQLite file (WAL): users, sessions, appointments
```

Why it is split this way: routers contain no logic, services contain no HTTP or SQL, and repositories contain
no business rules, so each layer can be tested alone (and is: see `tests/`). `create_app(settings)` takes an explicit
`Settings` object, so tests build an isolated app per test with its own database.

### The model

* **Features** (`app/ml/features.py`), all known at booking time: lead days (booking → visit), hour, weekday,
  appointment type, the patient's prior visit count, prior no-show count, a smoothed prior no-show rate, and a first-visit flag.
* **No label leakage.** Training rows are processed one day at a time and a visit only sees history from *earlier*
  days; tests cover the same-day and future-leak cases. The same encoder is used for training and serving.
* **Cold start.** A fresh clinic has no history, and the brief rules out external data. The model is bootstrapped
  from a documented simulator (`app/ml/synthetic.py`: longer lead time, repeat no-shows, early/late slots and
  Mon/Fri raise risk). Real reconciled appointments are added with 3× weight each time the model retrains
  (admin → *Retrain*), and open appointments are re-scored afterwards. **Until real data accumulates, the displayed
  accuracy describes the simulated baseline, not your clinic.** The Model tab says so.
* **Alert threshold.** At a ~20% base rate the default 0.5 cut-off misses most no-shows, so the threshold is chosen on a
  separate validation split: best F1 among cut-offs that flag at most 40% of appointments (an alert on most of the
  day gets ignored). Metrics are reported on a third, untouched test split. Risk is shown as Low / Medium / High
  with the percentage, and risk scores are probabilities, so "expected no-shows" is the sum of scores.
* **Failure mode.** If prediction ever fails, a transparent heuristic (patient's smoothed history) is used and the
  appointment is tagged `heuristic-fallback`, so entering data never breaks because of the model.

### Trade-off: model accuracy vs response time

Two model families are selectable with `MEDITRACK_MODEL_KIND`. `scripts/benchmark_models.py` trains both on identical
data and times prediction (median of repeated runs; `docs/benchmark.md` holds the committed output):

| Training rows | Model | AUC | F1 | Recall | Train (s) | 1-row predict (ms) | 200-row predict (ms) |
|---:|---|---:|---:|---:|---:|---:|---:|
| 2,000 | logistic | 0.660 | 0.413 | 0.457 | 0.10 | 0.22 | 0.23 |
| 2,000 | gbm | 0.602 | 0.359 | 0.518 | 0.27 | 1.85 | 3.09 |
| 6,000 | logistic | 0.656 | 0.401 | 0.589 | 0.11 | 0.22 | 0.23 |
| 6,000 | gbm | 0.646 | 0.399 | 0.585 | 0.37 | 1.99 | 3.40 |
| 20,000 | logistic | 0.666 | 0.410 | 0.561 | 0.17 | 0.24 | 0.31 |
| 20,000 | gbm | 0.665 | 0.413 | 0.571 | 0.29 | 0.50 | 0.88 |

Reading it honestly:

* On this data the simpler model is **as accurate or better and 2–8× faster** to predict. Gradient boosting only catches up
  at 20,000 rows, and never clearly wins. Even the best possible model (scoring with the simulator's hidden probabilities) reaches
  only AUC ≈ 0.78, so the ceiling is set by how noisy no-shows are, not by model capacity.
* Both are fast in absolute terms (≪ 10 ms), so latency is not a user-visible problem at one clinic's volume. The real cost of
  the heavier model is **explainability** (logistic exposes signed weights on the Model tab; boosting does not) and **small-data
  stability** (it overfits when real data is scarce).
* So the default is `logistic`. Switch to `gbm` once a clinic has many thousands of reconciled visits *and* a held-out
  comparison on real data shows a gain. Latency matters because a prediction happens synchronously on every save; the app scores a
  bulk upload in **one vectorised call**, and the dashboard (an aggregation over all rows) is the cached part.

### Caching

`GET /api/dashboard` is cached per (window, day) for 60 s (`X-Cache: HIT|MISS` header). **Every write invalidates the
whole cache**, so staff never see numbers that ignore an appointment they just reconciled. A generation counter stops a slow
computation that started before a write from storing its stale result afterwards (tested).

### Dashboard definitions

*Reconciled* = attended + no-show. *No-show rate* = no-shows ÷ reconciled; still-scheduled visits are excluded so today's
pending appointments don't look like attendance. *Rolling 7-day rate* smooths daily noise. *Predicted no-shows* = sum of the
scores stored when each appointment was created (what staff were told at the time), which also makes the
*prediction quality* panel an honest backtest.

## Security and correctness

* **Passwords:** scrypt (stdlib) with per-user salt; constant-time compare; unknown users cost the same time as wrong passwords.
  No default password exists in code: set via environment or a random one is generated and logged once. Minimum 10 characters.
* **Sessions:** random 256-bit token in an `HttpOnly`, `SameSite=Strict` cookie (`Secure` when `MEDITRACK_COOKIE_SECURE=true`); only the
  SHA-256 of the token is stored; expiry enforced server-side; logout revokes the session.
* **Brute force:** 5 failures per (username, client) per 5 minutes → 429.
* **RBAC:** every data route depends on `require(<permission>)`; `tests/test_rbac.py` checks *every endpoint against every role*.
* **Input validation:** pydantic models with `extra="forbid"`; names restricted to letters, spaces and `. ' -`; times within clinic hours;
  date ranges bounded; bulk uploads capped at 200 rows and saved all-or-nothing; duplicates rejected (409).
* **Injection:** all SQL is parameterised (the only interpolated fragment comes from a fixed allow-list); the UI builds DOM with text nodes, never `innerHTML`;
  CSV cells starting with `= + - @` are neutralised against spreadsheet formula injection.
* **Responses:** CSP (scripts/styles from self only), `nosniff`, `no-referrer`, `Cache-Control: no-store` on API responses; validation errors never echo submitted
  values; unexpected errors return a generic 500.

### Known limitations

* Sessions, the login throttle and the cache are in-process; running several workers would need Redis (or similar) for the latter two. SQLite is single-node by design here.
* Patient names are stored unencrypted and there is no audit log of reads; a real deployment would need both, plus HTTPS in front.
* No CSRF token: protection relies on `SameSite=Strict` plus JSON-only endpoints.
* The 40% alert cap is enforced on validation data; on a population that differs from it (my seeded demo flags about half of reconciled visits) the live flag rate can be higher.
* Not built (out of scope per the brief): user management UI, password change, external integrations.

## Repository layout

```
app/            config, schemas, db, security, cache, errors, deps, main
app/ml/         features, synthetic baseline, model service
app/services/   appointments, dashboard, reports
app/routers/    auth, appointments, reports, model
app/static/     index.html, styles.css, js/ (api, dom, bulk, charts, views/)
scripts/        seed_demo.py, benchmark_models.py
tests/          pytest suite · tests/js (node) · tests/e2e (optional Playwright smoke test)
docs/           benchmark.md
```

## Testing

128 pytest tests: validation rules, repositories (atomic batches, history), auth (hashing, throttling, expiry, sessions), feature
construction and leakage, model training and fallback, cache semantics, the full role × endpoint matrix, dashboard maths, CSV export
and formula injection, error handling and headers. Plus 5 node tests for the bulk-paste parser, and an optional Playwright script that
drives the real UI (sign-in, add, duplicate, bulk, reconcile, dashboard, export, auditor read-only, phone-width overflow).

## AI usage

AI was used initially to provide a high-level outline and starting project scaffolding from the assessment brief. From that baseline, the entire application was extensively redesigned, refined, debugged, and enhanced to build the complete production-grade system:

### 1. Complete UI/UX Redesign & Alignment
* **Design System:** Replaced the initial dark, cluttered theme with a clean, professional clinical dashboard aesthetic featuring medical light blues (`#f0f4f9`), crisp white cards (`#ffffff`), and midnight slate typography (`#0f172a`).
* **Header & Toolbar Alignment:** Reorganized fragmented controls into a unified `.dashboard-toolbar` and fixed KPI card text wrapping (preventing broken hyphenations like `PREDICTED NO-` / `SHOWS`).
* **Organized Appointment Scheduling:** Transformed the cramped, 50/50 side-by-side forms into a spacious card with a balanced 2-column grid (`.appointment-grid`) and clean tab switching between Single Appointment and Bulk Paste.
* **Clinical Data Tooltips:** Replaced informal emojis in hover tooltips with bespoke clinical dark-slate hover cards displaying exact metrics and percentages.
* **Pagination:** Added smooth client-side table pagination (8 rows/page) with previous/next controls and page pills for daily appointment lists.

### 2. Feature Additions & Enhancements
* **Required Patient Mobile Numbers:** Integrated a mandatory patient phone field across schemas (`AppointmentIn`), SQLite database migrations, and forms with smart auto-formatting for Indian mobile numbers (`9398242064` → `+91 93982 42064`).
* **Patient Privacy Masking & Eye Tool:** Implemented clinical PHI privacy masking (`+91 93••• ••064`) with interactive SVG eye toggles (`👁` to reveal, `👁️‍🗨️` to re-mask) per row, plus a master header toggle to reveal/mask all records simultaneously.
* **Historical Date Filtering & Form Locking:** Unlocked date filtering so staff can view and reconcile past records (e.g. yesterday's visits), while automatically disabling and locking the scheduling form with a prominent lock banner (`🔒 Appointment booking disabled for past dates`).
* **Realistic Seed Data:** Updated demo generators to populate 70 realistic patient profiles with authentic names and Indian mobile numbers across 330+ appointments.

### 3. Bugs Fixed & Security Hardening
* **Pydantic v2 Extra Input Error:** Fixed `patient_phone: Extra inputs are not permitted` by synchronizing schema models and enabling automatic server reloading (`--reload` default) on startup.
* **Past Booking Validation:** Fixed conflicting validations so users can freely navigate historical records while strictly blocking past time/date bookings.
* **Repository & Secrets Hardening:** Comprehensive `.gitignore` configuration ensuring all `.env`, `.env.*`, and SQLite database files are strictly ignored and prevented from being tracked in Git.
* **Test Suite Verification:** Maintained and expanded test coverage across schemas, RBAC, API endpoints, and validation rules to 100% pass rate (129 backend tests).
