"""Optional real MySQL+Django+mock+worker acceptance script.

Run AFTER starting MySQL, Django, and mock; this script uses --once workers itself.
Calls safe demo test endpoints, creates a new uniquely named workshop and cancels it.
"""
import os
import subprocess
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parents[1]
API = os.getenv('API_BASE_URL', 'http://127.0.0.1:8000').rstrip('/')

def request(method, path, token=None, payload=None, expected=(200,)):
    response = requests.request(method, API + path,
        headers={'Authorization': f'Bearer {token}'} if token else {},
        json=payload, timeout=8)
    assert response.status_code in expected, (path, response.status_code, response.text)
    return response.json()

def login(email):
    return request('POST', '/api/auth/login/',
                   payload={'email': email, 'password': 'Demo@12345'})['token']

def run_worker():
    subprocess.run([sys.executable, 'manage.py', 'notification_worker', '--once', '--batch', '20'],
                   cwd=str(ROOT / 'backend'), check=True, timeout=90)

def main():
    organizer = login('organizer@demo.local')
    alex = login('alex@demo.local')
    sam = login('sam@demo.local')
    assert request('GET', '/api/health/')['status'] == 'ok'
    new = request('POST', '/api/workshops/', token=organizer,
                  payload={'title': 'Acceptance Test ' + uuid.uuid4().hex[:8],
                           'description': 'End to end reliability test',
                           'starts_at': (datetime.now(timezone.utc) + timedelta(days=8)).isoformat(),
                           'capacity': 2}, expected=(201,))['workshop']
    wid = new['id']
    request('POST', '/api/mock/mode/', token=organizer, payload={'mode': 'always_503'})
    try:
        a = request('POST', f'/api/workshops/{wid}/register/', token=alex, expected=(201,))
        b = request('POST', f'/api/workshops/{wid}/register/', token=sam, expected=(201,))
        assert a['notification'] == 'QUEUED' and b['notification'] == 'QUEUED'
        assert request('POST', f'/api/workshops/{wid}/register/', token=alex,
                       expected=(409,))['error']
        run_worker()
        events = [e for e in request('GET', '/api/outbox/', token=organizer)['events']
                  if e['workshop_id'] == wid]
        assert len(events) == 2 and all(e['status'] == 'RETRY' for e in events), events
        print('PASS: registration commits without HTTP delivery; 503 results in RETRY')
        request('POST', '/api/mock/mode/', token=organizer, payload={'mode': 'healthy'})
        for e in events:
            request('POST', f'/api/outbox/{e["id"]}/retry/', token=organizer)
        run_worker()
        events = [e for e in request('GET', '/api/outbox/', token=organizer)['events']
                  if e['workshop_id'] == wid]
        assert all(e['status'] == 'DELIVERED' for e in events), events
        print('PASS: durable retry and confirmation for both members')
        assert request('POST', f'/api/workshops/{wid}/cancel/', token=organizer)['cancelled_now']
        assert not request('POST', f'/api/workshops/{wid}/cancel/', token=organizer)['cancelled_now']
        run_worker()
        events = [e for e in request('GET', '/api/outbox/', token=organizer)['events']
                  if e['workshop_id'] == wid]
        assert len(events) == 4 and all(e['status'] == 'DELIVERED' for e in events), events
        print('PASS: two cancellations, no duplicates, all four events delivered')
        receipt = request('GET', '/api/mock/deliveries/', token=organizer)['deliveries']
        keys = {e['event_key'] for e in events}
        assert keys.issubset({r['event_key'] for r in receipt})
        print('PASS: mock HTTP receipts include all event keys')
        print('ALL LIVE ACCEPTANCE CHECKS PASS')
    finally:
        request('POST', '/api/mock/mode/', token=organizer, payload={'mode': 'healthy'})

if __name__ == '__main__':
    main()
