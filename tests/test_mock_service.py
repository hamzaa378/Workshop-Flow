"""Runs against a real localhost HTTP server with an isolated SQLite delivery ledger.
No Django or MySQL required for this test module.
"""
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
import requests
import pytest

ROOT = Path(__file__).resolve().parents[1]
SECRET = 'fixture-secret-not-for-deployment'


def pick_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]

@pytest.fixture
def mock_server(tmp_path):
    port = pick_port()
    env = dict(os.environ, MOCK_PORT=str(port), MOCK_BIND_HOST='127.0.0.1',
               MOCK_SHARED_SECRET=SECRET, MOCK_DB_PATH=str(tmp_path / 'ledger.sqlite3'))
    args = [sys.executable, str(ROOT / 'mock_service' / 'server.py')]
    proc = subprocess.Popen(args, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    base = f'http://127.0.0.1:{port}'
    for _ in range(75):
        try:
            if requests.get(base + '/health', timeout=0.3).ok:
                break
        except requests.RequestException:
            time.sleep(0.1)
    else:
        proc.kill()
        raise RuntimeError('Mock server did not start')
    yield base, env, proc
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=4)
        except subprocess.TimeoutExpired:
            proc.kill()


def headers(key='registration:101:confirmed'):
    return {'X-Mock-Secret': SECRET, 'Idempotency-Key': key}

PAYLOAD = {'type': 'REGISTRATION_CONFIRMED', 'registration_id': 101,
           'recipient_email': 'alex@demo.local', 'workshop_id': 8}


def test_outage_recovery_and_idempotency(mock_server):
    base, _, _ = mock_server
    assert requests.get(base + '/status', timeout=2).status_code == 403
    h = headers()
    assert requests.post(base + '/control', json={'mode': 'always_503'}, headers=h).ok
    r = requests.post(base + '/notify', json=PAYLOAD, headers=h, timeout=3)
    assert r.status_code == 503
    assert requests.get(base + '/status', headers=h).json()['delivered_unique'] == 0
    assert requests.post(base + '/control', json={'mode': 'healthy'}, headers=h).ok
    assert requests.post(base + '/notify', json=PAYLOAD, headers=h, timeout=3).status_code == 200
    duplicated = requests.post(base + '/notify', json=PAYLOAD, headers=h, timeout=3).json()
    assert duplicated['duplicate'] is True
    assert requests.get(base + '/status', headers=h).json()['delivered_unique'] == 1


def test_flaky_eventually_responds_success(mock_server):
    base, _, _ = mock_server
    h = headers('registration:202:confirmed')
    requests.post(base + '/control', json={'mode': 'flaky'}, headers=h)
    statuses = [requests.post(base + '/notify', json=PAYLOAD, headers=h, timeout=3).status_code
                for _ in range(4)]
    assert statuses == [503, 503, 200, 200]
    assert requests.get(base + '/status', headers=h).json()['delivered_unique'] == 1


def test_ledger_survives_mock_restart(mock_server):
    base, env, proc = mock_server
    h = headers('registration:303:confirmed')
    assert requests.post(base + '/notify', json=PAYLOAD, headers=h, timeout=3).ok
    proc.terminate()
    proc.wait(timeout=4)
    second = subprocess.Popen([sys.executable, str(ROOT / 'mock_service' / 'server.py')],
                              env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(60):
            try:
                if requests.get(base + '/health', timeout=0.3).ok:
                    break
            except requests.RequestException:
                time.sleep(0.1)
        else:
            pytest.fail('Mock restart failed')
        data = requests.post(base + '/notify', json=PAYLOAD, headers=h, timeout=3).json()
        assert data['duplicate'] is True
        assert requests.get(base + '/status', headers=h).json()['delivered_unique'] == 1
    finally:
        second.terminate()
        second.wait(timeout=4)


def test_one_failed_member_does_not_block_another(mock_server):
    base, _, _ = mock_server
    h = headers()
    assert requests.post(base + '/control', json={'mode': 'flaky'}, headers=h).ok
    failed = requests.post(base + '/notify', json=PAYLOAD,
                           headers=headers('registration:401:confirmed'), timeout=3)
    assert failed.status_code == 503
    other_key = 'registration:402:confirmed'
    for _ in range(3):
        result = requests.post(base + '/notify', json=PAYLOAD, headers=headers(other_key), timeout=3)
    assert result.status_code == 200
    receipt = requests.get(base + '/deliveries', headers=h, timeout=3).json()['deliveries']
    assert any(r['event_key'] == other_key for r in receipt)
    assert not any(r['event_key'] == 'registration:401:confirmed' for r in receipt)


def test_timeout_creates_ambiguous_but_idempotent_delivery(mock_server):
    base, _, _ = mock_server
    h = headers('registration:501:confirmed')
    assert requests.post(base + '/control', json={'mode': 'timeout'}, headers=h).ok
    with pytest.raises(requests.exceptions.Timeout):
        requests.post(base + '/notify', json=PAYLOAD, headers=h, timeout=0.15)
    time.sleep(3.2)  # Server eventually records the receipt after client timed out.
    assert requests.post(base + '/control', json={'mode': 'healthy'}, headers=h).ok
    response = requests.post(base + '/notify', json=PAYLOAD, headers=h, timeout=3).json()
    assert response['duplicate'] is True
    assert requests.get(base + '/status', headers=h).json()['delivered_unique'] == 1
