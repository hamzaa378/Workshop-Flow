# Project handover and continuation guide — v1.0

**Challenge:** GDG TECH Wildcard Entry, Backend Task 2, Workshop Registration and Notifications (PDF page 7).

**Status:** Code and schema authored; Python syntax compile passed; 5 mock HTTP tests passed. SQL and Django/Streamlit integration await execution against a real MySQL 8 server. Avoid describing this as fully verified until running `verify_schema` and `tests/live_acceptance.py`.

## Decisions frozen for v1

- Stack: MySQL 8.0+; Django lightweight JSON API without DRF; separate Django management-command worker; Python stdlib mock HTTP server with SQLite dedup ledger; Streamlit frontend.
- MySQL SQL files own table creation and routines. Django models are `managed=False` and must remain consistent with `sql/01_schema.sql`.
- Three-role concepts simplified to two **roles**: `ORGANIZER`, `MEMBER`.
- Atomic registration/cancellation procedures plus triggers create persisted outbox events. No HTTP in web request or DB transactions.
- Confirmation-before-cancellation delivery ordering for each individual registration.
- Worker uses MySQL 8 `SKIP LOCKED`, short claim transactions, one event per claim, retry backoff SQL function, expiring leases.
- At-least-once transport; idempotent effects only with the included SQLite-backed mock receiver.
- No real mail/SMS: mock service is explicitly requested by challenge.

## All runtime components

1. `sql/00_database.sql`, `01_schema.sql`, `02_programmability.sql` create 6 tables + 3 views + 3 triggers + 3 stored procs + 2 functions (one repair proc uses cursor).
2. `backend/config/settings.py` dotenv/MySQL connection/UTC configuration.
3. `backend/core/models.py` SQL table mapping.
4. `backend/core/api.py` JSON endpoints, roles, input validation, SQL procedures, ownership checks, mock proxy.
5. `backend/core/auth.py` 8-hour signed bearer tokens.
6. `backend/core/delivery.py` worker algorithm and HTTP attempts.
7. `backend/core/management/commands/notification_worker.py` long-lived loop and transient DB reconnection.
8. `.../seed_demo.py` local fixtures and `.../verify_schema.py` installation verification.
9. `mock_service/server.py` independent HTTP implementation, failure injection, SQLite-backed delivery receipts.
10. `frontend/app.py` login, organizer creation/cancellation, member registration, notification queue, mock failure controls, audit, user guide.
11. `tests/test_mock_service.py`, `test_delivery_rules.py`, `live_acceptance.py` tests.
12. `scripts/*.bat`, `setup_windows.ps1`, `compose.yaml`, `.env.example` development setup.

## Next execution steps (highest priority)

1. Copy `.env.example` to `.env`, fill MYSQL_PASSWORD and unique secrets.
2. Install deps `pip install -r requirements.txt` in a virtualenv; ensure Python 3.11/3.12 and MySQL 8 are available.
3. Run SQL scripts 00, 01, 02 in order using MySQL CLI with `source`.
4. `cd backend; python manage.py verify_schema; python manage.py seed_demo`.
5. Start mock + Django API, run `python tests/live_acceptance.py`; fix any *observed* MySQL SQL dialect/runtime issues before marking PASS.
6. Start worker in another window and Streamlit. Manually test role controls, form behavior, success/failure, and restart recovery.
7. Run `pytest -q tests`, capture stdout and screenshots for submission.
8. Only after live verification, package/push source to GitHub; do not upload `.env`, `.sqlite3`, `.venv` or local credentials.

## Known limitations / next improvements

- No actual external SMTP/SMS; mock is suitable for task spec.
- Demo bearer tokens, no registration/signup flow, password reset, rate limiting, 2FA, HTTPS or public deployment policy. Add before production.
- MySQL/Streamlit not runnable in authoring environment, therefore no E2E PASS evidence currently.
- Real provider may not guarantee recipient-side idempotency. Retain unique event keys and integrate with provider policy.
- No permanent-failure/dead-letter handling, alerting, dashboards, multiple organizer account self-service or release orchestration.
- Historical audit events contain member IDs, but no field-level PIIs beyond outbox snapshot; introduce retention controls before public use.
- Full workshop list is capped at 200 rows in API; event list at 300 rows. Add pagination for larger deployments.

## Success definition

**v1 acceptance is complete** when `verify_schema` passes, `live_acceptance.py` passes against the user's MySQL instance, and Streamlit's register/cancel/retry/mode controls work in a browser. Those activities are **the remaining environment-dependent validation**, rather than missing core source modules.
