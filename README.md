# WorkshopFlow — GDG TECH Wildcard Entry, Backend Task 2

**Workshop Registration and Notifications** • MySQL 8.0+ • Django 5.2 • Streamlit • independent HTTP mock • durable background delivery worker

This is a substantial, runnable v1 implementation of **Backend Development → Task 2**, as described on page 7 of `GDG_Tech_Wildcard_Entry.pdf`. It focuses on correctness when notification delivery fails: registrations and cancellation events are committed in MySQL **before** HTTP is attempted. The API does **not** wait for the mock service.

> Local-dev project, not a production-hardened public deployment. The HTTP mock does not send real mail or SMS. Tests against an actual MySQL server require you to run the provided live acceptance script. Never submit example passwords or `.env` credentials to GitHub.

## Requirements coverage

| Challenge requirement | Implementation | How to demonstrate |
| --- | --- | --- |
| Organizer creates workshops | `POST /api/workshops/`, Streamlit organizer UI | Create new workshop |
| Member may register once per workshop | Unique `(workshop_id,member_id)` MySQL key, locking procedure | Register twice; second call returns 409 |
| Registration doesn't await notification | Registration procedure only writes SQL; worker sends separately | Put mock in `always_503`, registration still 201 |
| Every successful registration queues a confirmation | `AFTER INSERT` trigger creates outbox event within same SQL transaction | Inspect `notification_outbox` |
| Failed registration never queues a confirmation | SQL transaction rollback and trigger atomicity | Duplicate/full/cancelled registrations create no events |
| Survive Django / worker restart | Outbox is persisted in MySQL, not process memory | Stop/restart server/worker, deliver previously queued event |
| Retry unavailable mock service | Exponential retry, persisted due timestamps, leases | Use `always_503`, recover with `healthy` |
| One recipient's failure doesn't block others | Per-event HTTP results and independent retries | Test multiple members while `flaky`/`timeout` mode |
| Cancellation notifies all registered members | `AFTER UPDATE` workshop trigger inserts event for each registration | Cancel workshop and inspect all notification events |
| Mock HTTP errors and timeouts | Separate Python HTTP service; modes `healthy`,`flaky`,`always_503`,`timeout` | Toggle from organizer UI |
| Explain duplicate delivery | Event idempotency keys, unique SQLite receipt ledger | Post same event twice and inspect one receipt |

## Repository layout

```text
WorkshopFlow/
  .env.example              # local configuration template
  compose.yaml              # optional MySQL 8.4 only
  requirements.txt
  sql/
    00_database.sql          # create database
    01_schema.sql            # 6 InnoDB tables with FK/index/unique/check constraints
    02_programmability.sql   # 3 triggers, 3 procedures, 2 functions, 3 views, cursor
    03_verification_queries.sql
  backend/
    manage.py
    config/                  # Django connection, URL routing, WSGI
    core/
      models.py              # explicit models mapped to SQL-managed tables
      api.py                 # bearer-authenticated REST-style API
      auth.py                # expiring signed local tokens
      delivery.py            # durable outbox claim/send/finalize algorithm
      management/commands/
        seed_demo.py
        verify_schema.py
        notification_worker.py
  mock_service/server.py     # independent HTTP service, SQLite deduplication
  frontend/app.py            # functional Streamlit organizer/member dashboard
  tests/
    test_mock_service.py     # executable real HTTP reliability tests
    test_delivery_rules.py  # worker helper unit tests
    live_acceptance.py      # optional full MySQL+Django+mock E2E tests
  scripts/
    setup_windows.ps1
    start_api.bat
    start_mock.bat
    start_worker.bat
    start_frontend.bat
  docs/
    ARCHITECTURE.md
    RELIABILITY.md
    TEST_PLAN.md
    DB_REFERENCE.md
    HANDOVER.md
```

## Quick start — Windows 11 / PowerShell

**Prerequisites:** Python 3.11 or 3.12 recommended, MySQL Server **8.0+** (8.4 recommended), and the MySQL command-line client. Docker Desktop is optional. Four separate processes are used for Django API, mock provider, worker, and Streamlit.

From the **repository root**:

```powershell
# 1. Create Python virtual environment and install dependencies
powershell -ExecutionPolicy Bypass -File .\scripts\setup_windows.ps1

# 2. Edit .env with your own MySQL password and secrets
notepad .env
```

Replace `MYSQL_PASSWORD`, `DJANGO_SECRET_KEY`, `MOCK_SHARED_SECRET` with local values. Keep `DJANGO_DEBUG=true` for the demo seed, and **never** check `.env` into version control. Generate random secret strings using `python -c "import secrets; print(secrets.token_urlsafe(48))"`.

### Start MySQL and create SQL objects

Start your local MySQL Server Windows service. If you don't have MySQL installed, an optional Docker database is available:

```powershell
# Docker alternative (requires Docker Desktop; uses MYSQL_PASSWORD from .env)
docker compose --env-file .env up -d mysql
```

Apply the *three SQL files* in order, from the repo root with MySQL CLI on `PATH`:

```powershell
mysql -u root -p -e "source sql/00_database.sql"
mysql -u root -p -e "source sql/01_schema.sql"
mysql -u root -p -e "source sql/02_programmability.sql"
```

**PowerShell detail:** don't use Bash-style `mysql ... < file.sql` in older PowerShell, which may reject input redirection. The MySQL client's `source` command handles the SQL file, including `DELIMITER` in stored procedures and triggers.

If `mysql` is not recognized, add your local `MySQL Server 8.0\bin` (or `8.4\bin`) directory to `PATH`, or run the full executable path. Avoid running `02_programmability.sql` in a GUI driver that ignores MySQL client's `DELIMITER` directive.

### Verify and seed demo accounts

```powershell
cd backend
..\.venv\Scripts\python.exe manage.py verify_schema
..\.venv\Scripts\python.exe manage.py seed_demo
cd ..
```

`verify_schema` is read-only and should report **6/6 tables, 3/3 views, 3/3 triggers, 3/3 procedures and 2/2 functions**. `seed_demo` is idempotent; it creates three sample accounts and a workshop.

| Role | Email | Password (local demo only) |
| --- | --- | --- |
| Organizer | `organizer@demo.local` | `Demo@12345` |
| Member | `alex@demo.local` | `Demo@12345` |
| Member | `sam@demo.local` | `Demo@12345` |

### Start four services in four terminals

Run the `.bat` launchers from the root (double-click or invoke them in separate terminals):

```powershell
.\scripts\start_mock.bat      # http://127.0.0.1:9100
.\scripts\start_api.bat       # http://127.0.0.1:8000/api/health/
.\scripts\start_worker.bat    # continuous outbox processing
.\scripts\start_frontend.bat  # http://localhost:8501
```

Alternatively, run the Python commands directly:

```powershell
# terminal A, root
.\.venv\Scripts\python.exe mock_service\server.py
# terminal B, backend/
..\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000
# terminal C, backend/
..\.venv\Scripts\python.exe manage.py notification_worker
# terminal D, root
.\.venv\Scripts\streamlit.exe run frontend\app.py --server.port 8501
```

Open **http://localhost:8501** and log in with a demo account.

**Important:** `python manage.py migrate` is *not* the schema initialization path for this repository. SQL scripts intentionally own the schema and Django models use `managed=False`. This keeps tables, triggers and procedures in one source of truth.

## Demonstration in about five minutes

1. **Start services** and log in as organizer. Create a workshop with two seats.
2. In **Notification operations**, set mock mode to `always_503`.
3. Sign out, log in as Alex, register. Confirm API returns successful registration while provider remains down.
4. Try registering Alex again. The backend returns **409**; no second outbox event is created.
5. Log in as Sam and register. Both unique registrations produce outbox events; each failure is recorded in `delivery_attempts` and retried independently.
6. As organizer, inspect the queue (`RETRY`). Set mock to `healthy` and use **Retry now** or wait for backoff. Both become `DELIVERED`.
7. Cancel the workshop. Two cancellation notifications are queued, one per registered member; cancelling again doesn't create duplicates.
8. Test persistence: pause/stop the worker, create a fresh registration on a different workshop, restart Django + worker. The outstanding event is still in MySQL and dispatches after restart.
9. Inspect mock receipts. Repeated HTTP requests with the same event key produce **one** durable mock receipt.

See `docs/TEST_PLAN.md` for a scored acceptance matrix and automated commands.

## Tests

```powershell
# unit and black-box mock tests; Python and mock only (no MySQL needed)
.\.venv\Scripts\python.exe -m pytest -q tests

# schema verification: requires MySQL with all scripts applied
cd backend
..\.venv\Scripts\python.exe manage.py verify_schema
cd ..

# full actual MySQL + API + mock acceptance (starts its own --once workers)
# start MySQL, Django API and mock service first; dedicated continuous worker can be stopped
.\.venv\Scripts\python.exe tests\live_acceptance.py
```

**Verification performed during artifact creation:** Python bytecode/syntax compilation succeeded, and the five real-HTTP mock tests passed (`5 passed`). The provided MySQL acceptance suite has not been run in the authoring environment because a MySQL server / Django runtime was not available there. Don't report the live suite as PASS without running it on your machine.

## Technical highlights

- **Transactional outbox:** inserts into `registrations` and `notification_outbox` happen in the *same* SQL commit, driven by a trigger. Cancellation update and event fanout are also atomic.
- **No HTTP in database transactions:** worker picks due rows using `FOR UPDATE SKIP LOCKED`, claims a short lease, commits, then POSTs to `/notify`. All failure handling remains per event.
- **Crash recovery:** an `INFLIGHT` row with expired `lease_until` is claimable again. Failed rows use a DB-maintained retry schedule.
- **Idempotency:** the outbox event has an immutable unique key; mock provider inserts receipt with `INSERT OR IGNORE` into a persistent SQLite DB. Retry after a timeout or response-loss cannot create two mock delivery receipts.
- **Ordering:** for the same registration, cancellation delivery waits until its confirmation has been delivered. This isn't necessary for all apps, but avoids confusing message order.
- **Reconciliation:** an explicit cursor-based SQL repair routine can backfill absent cancellation outbox events without creating duplicate keys.
- **Transparent operations:** API exposes organizer-only outbox status, delivery attempts via SQL, retry-now control, mock controls, and audit entries.

## API endpoints

| Method | Path | Role | Description |
| --- | --- | --- | --- |
| GET | `/api/health/` | Public | DB connectivity |
| POST | `/api/auth/login/` | Public | Get signed bearer token |
| GET | `/api/me/` | Any | Current account |
| GET / POST | `/api/workshops/` | Any / organizer | List / create workshops |
| POST | `/api/workshops/{id}/register/` | Member | Atomic registration, returns 201 + QUEUED |
| POST | `/api/workshops/{id}/cancel/` | Owner organizer | Idempotent workshop cancellation |
| GET | `/api/workshops/{id}/registrants/` | Owner organizer | Registrant list |
| GET | `/api/registrations/mine/` | Member | Own registrations |
| GET | `/api/outbox/` | Organizer | Event queue and statuses |
| POST | `/api/outbox/{id}/retry/` | Organizer | Expedite due event, not in-flight |
| GET | `/api/stats/` | Organizer | Dashboard counts |
| GET | `/api/audit/` | Organizer | SQL audit log |
| GET | `/api/mock/status/` | Organizer | Proxy mock status |
| POST | `/api/mock/mode/` | Organizer | Set mock failure mode |
| GET | `/api/mock/deliveries/` | Organizer | Mock durable receipts |

Authorized requests use `Authorization: Bearer <token>`. The API does not use session cookies; JSON mutation endpoints are protected with a signed bearer token. The mock service also requires an independent `X-Mock-Secret` header and should run on loopback.

## SQL objects

`01_schema.sql`: `accounts`, `workshops`, `registrations`, `notification_outbox`, `delivery_attempts`, `activity_audit`.

`02_programmability.sql`: `sp_register_member`, `sp_cancel_workshop`, `sp_repair_missing_cancellation_events` (cursor); `fn_seats_remaining`, `fn_retry_delay_seconds`; `trg_registration_guard`, `trg_registration_outbox`, `trg_cancel_outbox`; `v_workshop_metrics`, `v_notification_queue_summary`, `v_member_registrations`. Detailed definitions are in `docs/DB_REFERENCE.md`.

## Scope and remaining hardening

This project implements the **competition's backend Task 2** as a functional local prototype. Before an internet-facing production deployment, add strong identity/SSO, login rate limits, account verification, TLS and secrets management, structured monitoring, provider circuit breakers, a permanent-failure/dead-letter policy, worker orchestration, and real external delivery integrations. **A generic external email/SMS provider is not guaranteed to support idempotency keys:** exactly-once effects here apply to the included mock ledger only; the delivery worker itself uses *at-least-once* attempts.

No evidence of a production load benchmark or successful live MySQL integration is claimed.
