# Notification reliability contract

## Guarantees and limitations

| Failure mode | System behavior |
|---|---|
| Registration rolled back, invalid, duplicated, full, or cancelled | No new persisted confirmation because trigger runs inside the failed transaction |
| Django crashes immediately after SQL commit | Outbox row remains; independently restarted worker later sends it |
| Mock returns 503 | One event switches to RETRY with backoff; other members are processed independently |
| Mock TCP unavailable | Network error captured in delivery attempt history; event retries |
| Mock hangs | Client times out, worker retries; if mock eventually recorded success, provider dedups next attempt |
| Worker dies before HTTP | INFLIGHT lease expires; another / restarted worker claims the row |
| Worker dies after HTTP success but before marking DELIVERED | Retry invokes same idempotency key; mock receipt stays unique |
| Two workers run | MySQL SKIP LOCKED claims prevent normal concurrent double claims; leases plus idempotency handle crashes |
| Organizer cancels twice | Second cancel returns cancelled_now=false; no second SQL transition or outbox fanout |
| Same member registers twice | Database unique key enforces one registration; second API call returns 409 |
| Different member notifications fail | Each event carries its own status, attempts and next due time; failed member does not permanently block others |
| MySQL temporarily disappears | Worker catches database errors, delays, and reconnects; durable data remains once DB returns |

## At least once vs exactly once

The backend implements **at-least-once dispatch**, not exactly-once network delivery. An HTTP POST and a MySQL commit cannot be made atomic without a cooperating receiver / distributed transaction. We accept repeat POSTs after ambiguous timeout or process crash.

The mock receiver uniquely persists an immutable `event_key` in SQLite. Repeat posts return HTTP 200 with `duplicate=true` and do **not** create another receipt. Thus **for this mock service**, the *delivery effect* is idempotent, even though HTTP calls can repeat.

A real email or SMS provider may not offer this guarantee. For production, use a provider with native idempotency support or your own deduplicating gateway, and clarify the consequences of possible repeated messages.

## Retry calculation

`fn_retry_delay_seconds(n) = min(300, 2 ^ min(max(n,1),9))` seconds.

| Failed attempt | Delay until retry |
| --- | ---: |
| 1 | 2 s |
| 2 | 4 s |
| 3 | 8 s |
| 4 | 16 s |
| 5 | 32 s |
| 6 | 64 s |
| 7 | 128 s |
| 8 | 256 s |
| 9+ | 300 s |

Retries are **unbounded** in v1 while the mock is unavailable. This is a conscious challenge-focused decision prioritizing eventual delivery after recovery. A production system would distinguish retryable errors (503/429) from permanent errors (400), add dead-letter review, monitoring and an operator reconciliation workflow.

## Lease tuning

Default HTTP timeout is 1.3 seconds. Lease duration is 15 seconds, comfortably larger than any one request. The worker claims events one by one, rather than claiming a large batch and burning other items' lease time while waiting on a slow recipient.

`NOTIFY_LEASE_SECONDS` must exceed `NOTIFY_HTTP_TIMEOUT + 3` as checked at startup. If you run an unusually high latency mock or slow host, increase the lease. A worker preempted longer than its lease can be superseded; its final database update is ignored if it no longer owns the claim. Receiver-side idempotency remains necessary.

## Cancellation ordering trade-off

To avoid confusing members with cancellation-before-confirmation messages, a cancellation event is eligible only when the corresponding registration confirmation has been marked delivered. If confirmations never succeed, cancellation for the *same member* remains waiting. Other members are independent. This trade-off is documented instead of pretending all cancellation notifications can be sent instantly during a permanent outage.

## Recovery commands

```powershell
# Read-only SQL queue status
mysql -u root -p -D gdg_workshops -e "SELECT status,event_type,COUNT(*) n FROM notification_outbox GROUP BY status,event_type;"

# Run one worker pass from backend/
..\.venv\Scripts\python.exe manage.py notification_worker --once

# Repair missing cancellation outbox events for a known cancelled workshop (cursor procedure)
mysql -u root -p -D gdg_workshops -e "CALL sp_repair_missing_cancellation_events(1);"
```

The last command is normally unnecessary: the cancellation trigger creates all expected events atomically. Never use repair for a workshop that is still open (it is a no-op).
