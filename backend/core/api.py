"""Minimal, explicit JSON API. All database-side business changes are transactional."""
import json
import os
from datetime import datetime
from functools import wraps
import requests
from django.contrib.auth.hashers import check_password
from django.db import connection, transaction, DatabaseError, IntegrityError
from django.db.models import Count, Q
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from .auth import ApiError, issue_token, protected
from .models import Account, ActivityAudit, NotificationOutbox, Registration, Workshop


def endpoint(methods):
    def outer(fn):
        @csrf_exempt  # Bearer-only JSON API; no ambient session/cookie credentials.
        @wraps(fn)
        def wrapped(request, *args, **kwargs):
            if request.method not in methods:
                return JsonResponse({'error': 'Method not allowed'}, status=405)
            try:
                return fn(request, *args, **kwargs)
            except ApiError as exc:
                return JsonResponse({'error': exc.message}, status=exc.status)
            except (json.JSONDecodeError, UnicodeDecodeError):
                return JsonResponse({'error': 'Malformed JSON request body.'}, status=400)
        return wrapped
    return outer

def body_json(request):
    if not request.body:
        return {}
    value = json.loads(request.body.decode('utf-8'))
    if not isinstance(value, dict):
        raise ApiError('Expected a JSON object.')
    return value

def isodt(value):
    return value.isoformat() if value else None

def workshop_json(w, counts=None):
    count = counts if counts is not None else Registration.objects.filter(workshop_id=w.id).count()
    return {'id': w.id, 'title': w.title, 'description': w.description,
            'starts_at': isodt(w.starts_at), 'status': w.status,
            'capacity': w.capacity, 'registrations': count,
            'seats_left': None if w.capacity is None else max(0, w.capacity-count),
            'created_by_id': w.created_by_id, 'cancelled_at': isodt(w.cancelled_at)}

def event_json(event):
    return {'id': event.id, 'event_key': event.event_key, 'event_type': event.event_type,
            'workshop_id': event.workshop_id, 'registration_id': event.registration_id,
            'member_id': event.member_id, 'recipient_email': event.payload.get('recipient_email'),
            'status': event.status, 'attempts': event.attempts,
            'next_attempt_at': isodt(event.next_attempt_at),
            'delivered_at': isodt(event.delivered_at),
            'last_http_status': event.last_http_status, 'last_error': event.last_error}

def db_error(exc):
    raw = str(exc)
    for code, message in [('1062', 'Member is already registered for this workshop.'),
                          ('WORKSHOP_FULL', 'Workshop is full.'),
                          ('WORKSHOP_NOT_OPEN', 'Workshop is not open.'),
                          ('WORKSHOP_NOT_FOUND', 'Workshop was not found.'),
                          ('NOT_WORKSHOP_OWNER', 'Only the workshop owner can cancel it.'),
                          ('MEMBER_ROLE_REQUIRED', 'Only members may register.')]:
        if code in raw:
            return ApiError(message, 409 if code in ('1062', 'WORKSHOP_FULL', 'WORKSHOP_NOT_OPEN') else 403 if code == 'NOT_WORKSHOP_OWNER' else 404 if code == 'WORKSHOP_NOT_FOUND' else 400)
    return None

@endpoint(['GET'])
def health(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1')
            cursor.fetchone()
        return JsonResponse({'status': 'ok', 'database': 'connected'})
    except DatabaseError:
        return JsonResponse({'status': 'degraded', 'database': 'unavailable'}, status=503)

@endpoint(['POST'])
def login(request):
    data = body_json(request)
    email = str(data.get('email', '')).strip().lower()
    password = str(data.get('password', ''))
    account = Account.objects.filter(email=email).first()
    if not account or not check_password(password, account.password_hash):
        raise ApiError('Incorrect email or password.', 401)
    return JsonResponse({'token': issue_token(account), 'user':
                         {'id': account.id, 'email': account.email,
                          'full_name': account.full_name, 'role': account.role}})

@endpoint(['GET'])
@protected()
def me(request, user):
    return JsonResponse({'user': {'id': user.id, 'email': user.email,
                                  'full_name': user.full_name, 'role': user.role}})

@endpoint(['GET', 'POST'])
@protected()
def workshops(request, user):
    if request.method == 'GET':
        rows = Workshop.objects.all().annotate(registration_count=Count('registration')).order_by('-created_at')[:200]
        return JsonResponse({'workshops': [workshop_json(w, w.registration_count) for w in rows]})
    if user.role != 'ORGANIZER':
        raise ApiError('Only organizers may create workshops.', 403)
    data = body_json(request)
    title = str(data.get('title', '')).strip()
    description = str(data.get('description', '')).strip()
    if not 3 <= len(title) <= 180:
        raise ApiError('Workshop title must be 3–180 characters.')
    if len(description) > 2000:
        raise ApiError('Description is too long (max 2000 characters).')
    try:
        starts_at = datetime.fromisoformat(str(data['starts_at']).replace('Z', '+00:00'))
        if timezone.is_naive(starts_at):
            raise ValueError('timezone required')
        if starts_at <= timezone.now():
            raise ValueError('must be in future')
    except (ValueError, KeyError, TypeError):
        raise ApiError('starts_at must be a future ISO-8601 datetime with timezone.')
    capacity = data.get('capacity')
    if capacity in ('', None):
        capacity = None
    else:
        if isinstance(capacity, bool) or not str(capacity).isdigit() or not 1 <= int(capacity) <= 100000:
            raise ApiError('Capacity must be a positive integer up to 100000 or blank.')
        capacity = int(capacity)
    with transaction.atomic():
        workshop = Workshop.objects.create(created_by=user, title=title, description=description,
                                            starts_at=starts_at, capacity=capacity,
                                            status='OPEN')
        ActivityAudit.objects.create(actor=user, action='WORKSHOP_CREATED',
                                     entity_type='workshop', entity_id=workshop.id,
                                     details={'title': title})
    return JsonResponse({'workshop': workshop_json(workshop, 0)}, status=201)

@endpoint(['POST'])
@protected('MEMBER')
def register(request, user, workshop_id):
    # Procedure locks workshop FOR UPDATE, preventing last-seat and cancellation races.
    try:
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute('CALL sp_register_member(%s, %s, @registration_id)',
                               [user.id, workshop_id])
                while cursor.nextset():
                    pass
                cursor.execute('SELECT @registration_id')
                registration_id = cursor.fetchone()[0]
            # Trigger already wrote a PENDING confirmation in the same transaction.
        return JsonResponse({'registration_id': registration_id, 'workshop_id': workshop_id,
                             'status': 'REGISTERED', 'notification': 'QUEUED'}, status=201)
    except (IntegrityError, DatabaseError) as exc:
        mapped = db_error(exc)
        if mapped:
            raise mapped
        raise

@endpoint(['POST'])
@protected('ORGANIZER')
def cancel(request, user, workshop_id):
    try:
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute('CALL sp_cancel_workshop(%s, %s, @changed)', [workshop_id, user.id])
                while cursor.nextset():
                    pass
                cursor.execute('SELECT @changed')
                changed = bool(cursor.fetchone()[0])
        return JsonResponse({'workshop_id': workshop_id, 'cancelled_now': changed,
                             'status': 'CANCELLED', 'notifications': 'QUEUED' if changed else 'ALREADY_QUEUED'})
    except DatabaseError as exc:
        mapped = db_error(exc)
        if mapped:
            raise mapped
        raise

@endpoint(['GET'])
@protected('ORGANIZER')
def registrants(request, user, workshop_id):
    if not Workshop.objects.filter(id=workshop_id, created_by_id=user.id).exists():
        raise ApiError('Workshop not found or not owned by you.', 404)
    regs = Registration.objects.filter(workshop_id=workshop_id).select_related('member').order_by('id')
    return JsonResponse({'registrants': [{'registration_id': r.id, 'name': r.member.full_name,
                                          'email': r.member.email, 'registered_at': isodt(r.registered_at)}
                                         for r in regs]})

@endpoint(['GET'])
@protected('MEMBER')
def my_registrations(request, user):
    regs = Registration.objects.filter(member_id=user.id).select_related('workshop').order_by('-registered_at')
    return JsonResponse({'registrations': [{'id': r.id, 'workshop_id': r.workshop_id,
                                             'title': r.workshop.title, 'workshop_status': r.workshop.status,
                                             'registered_at': isodt(r.registered_at)} for r in regs]})

@endpoint(['GET'])
@protected('ORGANIZER')
def outbox(request, user):
    state = request.GET.get('status', '').upper()
    qs = NotificationOutbox.objects.filter(workshop__created_by_id=user.id)
    if state and state in {'PENDING', 'RETRY', 'INFLIGHT', 'DELIVERED'}:
        qs = qs.filter(status=state)
    return JsonResponse({'events': [event_json(e) for e in qs.order_by('-id')[:300]]})

@endpoint(['POST'])
@protected('ORGANIZER')
def retry_event(request, user, event_id):
    # No alteration to an active lease: a different worker may be delivering it.
    updated = NotificationOutbox.objects.filter(id=event_id, workshop__created_by_id=user.id,
                                                 status__in=['RETRY', 'PENDING']).update(
        next_attempt_at=timezone.now(), status='RETRY')
    if not updated:
        raise ApiError('Only your pending/retry events can be expedited.', 409)
    return JsonResponse({'event_id': event_id, 'retry_scheduled': True})

@endpoint(['GET'])
@protected('ORGANIZER')
def stats(request, user):
    scoped = NotificationOutbox.objects.filter(workshop__created_by_id=user.id)
    counts = {s: 0 for s in ('PENDING', 'INFLIGHT', 'RETRY', 'DELIVERED')}
    for row in scoped.values('status').annotate(total=Count('id')):
        counts[row['status']] = row['total']
    return JsonResponse({'workshops': Workshop.objects.filter(created_by_id=user.id).count(),
                         'registrations': Registration.objects.filter(workshop__created_by_id=user.id).count(),
                         'notifications': counts})

@endpoint(['GET'])
@protected('ORGANIZER')
def audit(request, user):
    audit_rows = ActivityAudit.objects.filter(
        Q(actor_id=user.id) | Q(entity_type='registration', entity_id__in=
                                  Registration.objects.filter(workshop__created_by_id=user.id).values('id'))
    ).order_by('-id')[:100]
    return JsonResponse({'audit': [{'id': r.id, 'action': r.action, 'entity_type': r.entity_type,
                                    'entity_id': r.entity_id, 'details': r.details,
                                    'created_at': isodt(r.created_at)} for r in audit_rows]})

def mock_call(method, path, payload=None):
    base = os.environ.get('MOCK_BASE_URL', 'http://127.0.0.1:9100').rstrip('/')
    headers = {'X-Mock-Secret': os.environ.get('MOCK_SHARED_SECRET', '')}
    try:
        response = requests.request(method, base + path, headers=headers, json=payload, timeout=2)
        response.raise_for_status()
        return JsonResponse(response.json())
    except (requests.RequestException, ValueError):
        return JsonResponse({'error': 'Mock service is unavailable.'}, status=503)

@endpoint(['GET'])
@protected('ORGANIZER')
def mock_status(request, user):
    return mock_call('GET', '/status')

@endpoint(['POST'])
@protected('ORGANIZER')
def mock_mode(request, user):
    data = body_json(request)
    mode = str(data.get('mode', ''))
    if mode not in ('healthy', 'always_503', 'timeout', 'flaky'):
        raise ApiError('Valid modes: healthy, always_503, timeout, flaky.')
    return mock_call('POST', '/control', {'mode': mode})

@endpoint(['GET'])
@protected('ORGANIZER')
def mock_deliveries(request, user):
    return mock_call('GET', '/deliveries')
