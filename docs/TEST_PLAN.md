# Acceptance and demo test plan

## Test evidence available from packaged files

- **Actual automated result in authoring environment:** `python -m pytest -q tests/test_mock_service.py` → **5 passed** (outage/recovery and deduplication; flaky recovery; SQLite ledger restart persistence; independent members; ambiguous timeout recovery).
- **Actual static result:** `python -m compileall -q backend frontend mock_service` → success.
- **Not executed in authoring environment:** full MySQL/Django API integration, SQL procedures and triggers, Streamlit browser interactions. The authoring sandbox does not have a MySQL server or Django/Streamlit installed. Run the remaining items on the target Windows development computer before submission.

## Live acceptance matrix

| ID | Action | Expected verifiable result |
| --- | --- | --- |
| A01 | `manage.py verify_schema` | 6 tables, 3 views, 3 triggers, 3 procs, 2 functions |
| A02 | Organizer creates workshop | 201; workshop appears in listing |
| A03 | Alex registers for workshop | 201; one registration and one pending confirmation |
| A04 | Alex registers again | 409; no second registration/confirmation |
| A05 | Organizer/member authorization check | Members cannot cancel; organizers cannot register as members; 403 |
| A06 | Set capacity 2 and add Alex + Sam | 201 each; all later distinct members rejected when full |
| A07 | Mock mode `always_503`; register on new workshop | Registration still commits 201 promptly; worker logs HTTP_ERROR and RETRY |
| A08 | Mock mode `healthy`; allow worker/force retry | Retry event becomes DELIVERED and receipt appears |
| A09 | Mock `flaky` | First two requests 503, later request 200, only one unique receipt |
| A10 | Mock `timeout` then `healthy` | TIMEOUT logged, retry eventually succeeds; no duplicate receipt |
| A11 | Stop worker, register, restart worker | Pending MySQL event survives and later delivers |
| A12 | Stop Django API after saving registration, restart API and worker | Existing event persists and is delivered |
| A13 | Organizer cancels 2-member workshop | Two cancellation events (1/member), eventually delivered |
| A14 | Organizer cancels it again | No additional events, `cancelled_now=false` |
| A15 | Try registering after cancellation | 409; no registration/outbox row added |
| A16 | Two worker processes | Each eventual event has single success receipt; logs may show retries |
| A17 | Force replay of same mock `event_key` | HTTP 200 with `duplicate=true`, mock unique receipt count unchanged |
| A18 | Query reporting views | Counts correspond to workshop registrations/outbox |
| A19 | Execute cursor reconciliation twice on cancelled workshop | No new duplicate cancellation event keys |
| A20 | Streamlit organizer and member UI | Forms submit and reflect API state; switching roles hides wrong controls |

## Automated full-stack scenario

Run MySQL and SQL scripts; then seed demo users and start Django **and mock**. Do not require a continuous worker: the test starts `notification_worker --once` on demand so it controls the error-recovery sequence.

```powershell
.\.venv\Scripts\python.exe tests\live_acceptance.py
```

It asserts: saved registration while mock is in `always_503`, duplicate rejection, both failure events marked RETRY after worker pass, successful delivery after restoring mock and scheduling retry, idempotent cancellation producing exactly one event per member, successful cancellation delivery, presence of mock receipts. Each run creates a new uniquely titled workshop and leaves audit evidence; run in a development DB.

## Manual restart scenario

1. Stop the continuous delivery worker while leaving Django and mock up.
2. Register a new member on a fresh workshop.
3. Inspect `SELECT * FROM v_notification_queue_summary` and observe PENDING.
4. Stop Django as well. Do **not** delete MySQL database or `.sqlite3` ledger.
5. Restart Django, mock and worker.
6. Observe transition PENDING → INFLIGHT → DELIVERED and exactly one mock receipt.

## Failure injection

| Mode | Response behavior | Worker interpretation |
| --- | --- | --- |
| `healthy` | HTTP 200 | DELIVERED |
| `always_503` | HTTP 503 | RETRY with saved backoff |
| `flaky` | HTTP 503 twice per new event then 200 | RETRY → success |
| `timeout` | Sleeps 3 s and then commits a mock receipt, possibly after client gave up | TIMEOUT then idempotent success on retry |

The timeout mode intentionally demonstrates an ambiguous response: the client may never receive 200, though the mock may commit a receipt. That's why retry idempotency is required.

## Reporting

Paste **actual** `verify_schema`, `pytest`, `live_acceptance`, and Streamlit screenshots into the GDG submission. Do not label this file an observed E2E success until those scripts have been run locally. The challenge Task 2 requests a reliability demonstration, not a 10k/s load report (which belongs to Backend Task 1).
