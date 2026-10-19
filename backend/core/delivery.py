"""Durable outbox dispatcher with short transactional claims and retryable HTTP.

Guarantee: at-least-once HTTP requests. Exactly-once mock EFFECT achieved through
recipient-side idempotency keyed by the immutable event_key. An external provider
would need to honor the same idempotency contract.
"""
import logging
import os
import socket
import time
import uuid
from dataclasses import dataclass
from datetime import timedelta
import requests
from django.db import transaction, connection
from django.db.models import Q
from django.utils import timezone
from .models import DeliveryAttempt, NotificationOutbox

logger = logging.getLogger(__name__)
WORKER_ID = f'{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:8]}'

@dataclass
class SendResult:
    success: bool
    outcome: str
    status_code: int | None
    error: str
    latency_ms: int

def classify_response(status_code):
    return 200 <= status_code < 300

def retry_delay(attempts):
    """Python mirror of MySQL fn_retry_delay_seconds, used as a safety fallback."""
    return min(300, 2 ** min(max(attempts, 1), 9))

def claim_events(batch_size=20, lease_seconds=15, worker_id=WORKER_ID):
    """Lock, claim, commit; never hold a DB lock across network I/O."""
    now = timezone.now()
    due = (Q(status__in=['PENDING', 'RETRY'], next_attempt_at__lte=now) |
           Q(status='INFLIGHT', lease_until__lte=now))
    claimed = []
    with transaction.atomic():
        # MySQL 8+ SKIP LOCKED permits multiple workers without blocking each other.
        candidates = (NotificationOutbox.objects.select_for_update(skip_locked=True)
                      .filter(due).order_by('next_attempt_at', 'id')[:batch_size * 3])
        for event in candidates:
            if len(claimed) >= batch_size:
                break
            if event.event_type == 'WORKSHOP_CANCELLED':
                # Preserve confirmation-before-cancellation delivery per member.
                if NotificationOutbox.objects.filter(
                    registration_id=event.registration_id,
                    event_type='REGISTRATION_CONFIRMED'
                ).exclude(status='DELIVERED').exists():
                    continue
            event.status = 'INFLIGHT'
            event.claimed_by = worker_id
            event.lease_until = now + timedelta(seconds=lease_seconds)
            event.save(update_fields=['status', 'claimed_by', 'lease_until', 'updated_at'])
            claimed.append(event)
    return claimed

def send_notification(event, session=None, timeout=1.3):
    """Dispatch outside of a DB transaction; request carries stable idempotency key."""
    session = session or requests
    base = os.environ.get('MOCK_BASE_URL', 'http://127.0.0.1:9100').rstrip('/')
    headers = {'Content-Type': 'application/json',
               'X-Mock-Secret': os.environ.get('MOCK_SHARED_SECRET', ''),
               'Idempotency-Key': event.event_key}
    started = time.monotonic()
    try:
        response = session.post(base + '/notify', json=event.payload, headers=headers, timeout=timeout)
        latency = max(0, int((time.monotonic() - started) * 1000))
        ok = classify_response(response.status_code)
        return SendResult(ok, 'SUCCESS' if ok else 'HTTP_ERROR', response.status_code,
                          '' if ok else f'HTTP {response.status_code}: {response.text[:250]}', latency)
    except requests.exceptions.Timeout:
        return SendResult(False, 'TIMEOUT', None, 'Notification request timed out',
                          max(0, int((time.monotonic() - started) * 1000)))
    except requests.exceptions.RequestException as exc:
        return SendResult(False, 'NETWORK_ERROR', None, f'{type(exc).__name__}: {str(exc)[:250]}',
                          max(0, int((time.monotonic() - started) * 1000)))

def finish_delivery(event, result, worker_id=WORKER_ID):
    """Only the owner of an active lease may finalize the event."""
    with transaction.atomic():
        locked = NotificationOutbox.objects.select_for_update().get(pk=event.pk)
        if locked.status != 'INFLIGHT' or locked.claimed_by != worker_id:
            logger.warning('Lost lease for event %s, ignoring stale result', event.pk)
            return False
        attempt_number = locked.attempts + 1
        DeliveryAttempt.objects.create(outbox=locked, attempt_number=attempt_number,
            outcome=result.outcome, http_status=result.status_code,
            latency_ms=result.latency_ms, error_message=result.error[:500])
        locked.attempts = attempt_number
        locked.last_http_status = result.status_code
        locked.last_error = None if result.success else result.error[:500]
        locked.claimed_by = None
        locked.lease_until = None
        if result.success:
            locked.status = 'DELIVERED'
            locked.delivered_at = timezone.now()
        else:
            with connection.cursor() as cursor:
                cursor.execute('SELECT fn_retry_delay_seconds(%s)', [attempt_number])
                delay = int(cursor.fetchone()[0])
            locked.status = 'RETRY'
            locked.next_attempt_at = timezone.now() + timedelta(seconds=delay)
        locked.save(update_fields=['status', 'attempts', 'last_http_status', 'last_error',
                                   'claimed_by', 'lease_until', 'delivered_at',
                                   'next_attempt_at', 'updated_at'])
    return True

def work_once(batch_size=20, timeout=1.3, lease_seconds=15):
    # Claim one event immediately before sending it. A big batch cannot consume
    # the remaining events' leases while waiting on earlier HTTP timeouts.
    count = 0
    for _ in range(batch_size):
        claimed = claim_events(batch_size=1, lease_seconds=lease_seconds)
        if not claimed:
            break
        event = claimed[0]
        result = send_notification(event, timeout=timeout)
        finish_delivery(event, result)
        logger.info('event=%s type=%s outcome=%s code=%s', event.id, event.event_type,
                    result.outcome, result.status_code)
        count += 1
    return count
