# MySQL schema and programmable objects

**Version:** v1.0. **Engine:** MySQL 8.0+ InnoDB, `utf8mb4`, UTC timestamps; Django manages no migrations for these six tables.

## Tables

| Table | Meaning | Constraints / key indexes |
| --- | --- | --- |
| `accounts` | Local organizer/member identities | unique email, role enum, password hash |
| `workshops` | Workshop details, capacity, cancellation | organizer FK, status/date index, capacity CHECK |
| `registrations` | Saved member commitments | unique `(workshop_id, member_id)`, both FKs |
| `notification_outbox` | Persisted message intent and delivery state | unique `event_key`, unique `(registration_id,event_type)`, due and lease indexes |
| `delivery_attempts` | One historical HTTP attempt per finalized work unit | unique `(outbox_id,attempt_number)` |
| `activity_audit` | Workshop create, registration, cancellation events | actor FK, entity indexes |

No normalization violations involving a repeated member email: the underlying member email is stored only in `accounts`, while the outbox JSON contains an intentionally immutable *delivery-time snapshot* of the address and workshop title for correct historical notification content.

### Outbox lifecycle

```text
PENDING -> INFLIGHT -> DELIVERED
           |
           +--> RETRY -> INFLIGHT -> ...
                ^
                |
       operator moves next_attempt_at to NOW
```

An abandoned `INFLIGHT` event is retried once its lease expires; no in-memory message queue is used.

## Triggers

- `trg_registration_guard` — validates OPEN workshop and MEMBER role; capacity checked by stored procedure and trigger.
- `trg_registration_outbox` — inserts confirmation and audit within original registration SQL transaction.
- `trg_cancel_outbox` — enqueues cancellation for all registered members only for first status transition `OPEN → CANCELLED`; inserts audit.

## Stored procedures

`sp_register_member(member_id, workshop_id, OUT registration_id)` serializes with `SELECT ... FOR UPDATE`, validates availability/capacity/role, inserts registration; outbox trigger fires automatically. The caller must own and commit/rollback the transaction.

`sp_cancel_workshop(workshop_id, organizer_id, OUT changed)` locks workshop, enforces owner role at the API layer and owner ID at the database layer, updates state only once, letting cancellation trigger fan out events. Caller owns transaction.

`sp_repair_missing_cancellation_events(workshop_id)` explicitly declares/opens/fetches/closes a **MySQL cursor** over registrations of one cancelled workshop. It uses `INSERT IGNORE` and outbox unique keys for idempotent event backfill. This is a maintenance/reconciliation routine, not the normal delivery path.

## Functions

- `fn_seats_remaining(workshop_id)` returns available seats, `-1` for unlimited, `-2` for unknown workshop ID.
- `fn_retry_delay_seconds(attempt)` returns capped exponential retry delay (seconds). The actual worker calls it on HTTP failures.

## Views

- `v_workshop_metrics` — registration counts, remaining seats, notification completion by workshop.
- `v_notification_queue_summary` — count per `(status,event_type)`, combined attempt count and earliest due retry.
- `v_member_registrations` — member/workshop joined registration reporting.

## Schema lifecycle

1. `sql/00_database.sql`: creates `gdg_workshops`.
2. `sql/01_schema.sql`: creates all six tables in FK-safe order, `IF NOT EXISTS`.
3. `sql/02_programmability.sql`: drops/recreates app routines/triggers/views (rerunnable on an existing instance, though pause writes during rollout).
4. `python manage.py verify_schema`: read-only assertion of all required objects, plus function smoke check.
5. `python manage.py seed_demo`: idempotent local fixture data.

**Do not change SQL schema independently of mapped Django models.** Database schema has SQL as the source of truth; Django models are `managed=False`. Don't run generated Django migrations to recreate these tables.

The schema has six tables, three views, three triggers, three procedures (one uses a cursor), and two functions. Stored routines and foreign keys require an appropriately privileged SQL user during installation. For a local demo, `root` works; production should separate a migration/DDL principal from a lower privilege runtime principal.
