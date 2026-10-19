# Architecture and service boundaries

## System diagram

```text
                            +-----------------------+
                            | Streamlit UI :8501    |
                            | organizer / member    |
                            +-----------+-----------+
                                        |
                                 HTTPS/JSON in prod
                                        |
                            +-----------v-----------+
                            | Django API :8000      |
                            | role + token checks   |
                            +-----------+-----------+
                                        |
                              atomic SQL transactions
                                        |
                      +-----------------v-----------------+
                      | MySQL 8 / gdg_workshops           |
                      | workshops, registrations          |
                      | transaction-bound OUTBOX triggers |
                      | due-event indexes / leases       |
                      +-----------------+-----------------+
                                        ^
                                        | claim + settle SQL
                            +-----------+-----------+
                            | Django worker process |
                            | retry / lease / audit |
                            +-----------+-----------+
                                        |
                              HTTP POST /notify
                                        |
                            +-----------v-----------+
                            | HTTP mock :9100       |
                            | failure modes         |
                            | SQLite dedup ledger   |
                            +-----------------------+
```

The four runtime service processes are Streamlit, Django API, background worker, and independent mock provider. MySQL is a fifth runtime dependency.

## Business transaction: registration

1. Validate signed member token and request input.
2. Django enters `transaction.atomic()`.
3. Call `sp_register_member(member_id, workshop_id, OUT registration_id)`.
4. Procedure performs `SELECT ... FOR UPDATE` on the workshop row. This serializes registration/cancellation and capacity checks per workshop.
5. Insert into `registrations`. Unique index blocks duplicate member/workshop pairs.
6. MySQL `trg_registration_outbox` inserts an event in `notification_outbox`, plus audit record. All three rows share the transaction.
7. Commit and return HTTP 201 with `notification: QUEUED`. **There is no outbound network call in steps 1–7.**
8. Independently, worker sends HTTP to mock. MySQL is updated after HTTP returns, not inside the original registration transaction.

If step 4–6 fails, the transaction rolls back, and **no confirmation outbox event survives**.

## Business transaction: cancellation

1. Owner organizer calls cancel endpoint.
2. `sp_cancel_workshop` locks the workshop row and verifies ownership.
3. Update `status=CANCELLED` once.
4. AFTER UPDATE trigger atomically inserts one cancellation event per existing registration using `INSERT ... SELECT`, plus audit record.
5. Commit. Second cancellation does not transition state and inserts no new notifications.

Concurrent registration and cancellation serialize on the **same workshop row** and therefore have well-defined ordering: a registration committed before cancellation receives a cancellation event; a registration attempted after cancellation fails.

## Delivery engine

- `claim_events` selects due rows with `SELECT ... FOR UPDATE SKIP LOCKED`. An event is marked `INFLIGHT` with `claimed_by` and `lease_until` before the transaction commits.
- `work_once` claims **one** item immediately before HTTP POST. This avoids leaving additional events' leases ticking down while an earlier HTTP request times out.
- The request includes `Idempotency-Key: registration:{registration_id}:confirmed` or `registration:{registration_id}:cancelled`.
- HTTP 2xx means success. Any other status, network error, or timeout means retry; `fn_retry_delay_seconds(attempt_number)` calculates exponential backoff capped at five minutes.
- An expired lease is claimable after a worker crash.
- On success, the worker sets `status=DELIVERED`, records a delivery attempt and timestamp. The outcome and attempt increment are committed together.
- Within one registration, cancellation is not sent until that registration's confirmation has reached `DELIVERED`. Events for different members are independent.

### Why outbox instead of `transaction.on_commit()` + HTTP?

`on_commit()` avoids sending before commit but is still process-local. If Django dies after commit and before invoking its callback, the HTTP request is lost. The persisted outbox makes the event discoverable by any future worker.

### Why not send HTTP from a trigger/procedure?

Database triggers must be fast and atomic, and HTTP isn't transactional with MySQL. Combining them would block registrations and create commit ambiguities when external services time out. SQL triggers only create *durable delivery intent*, not network side effects.

## Multiple workers

You can start more than one `notification_worker` process on MySQL 8. Each process gets a unique worker ID, and row-level `SKIP LOCKED` claims avoid the same event being claimed simultaneously. Crashes and lease expiry can still produce repeat HTTP requests, so the mock must be idempotent.

## Security boundary

- Auth is a signed, expiring bearer token, never inferred from a user-controlled member ID.
- Member endpoints cannot create/cancel workshops or inspect other members' data.
- Organizer cancellation and monitoring are limited to owned workshops.
- MySQL API interactions use parameterized SQL, or the Django ORM.
- Mock `/notify`, `/status`, `/control`, `/deliveries` require a shared secret; bind mock to `127.0.0.1` in development.
- No internet-facing deployment, cookie-based session auth, account signup, or real email is supplied in v1.
