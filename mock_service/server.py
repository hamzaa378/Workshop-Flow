"""Independent mock HTTP notification provider. SQLite makes deduplication survive restarts.

Modes:
  healthy: always 200
  always_503: always 503, no delivery
  timeout: sleep longer than worker timeout; may succeed after client disconnect
  flaky: first two attempts per event fail 503, subsequent requests succeed

All routes except /health require X-Mock-Secret; binds to loopback by default.
"""
import json
import os
import sqlite3
import sys
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / '.env')
DB_PATH = Path(os.getenv('MOCK_DB_PATH', 'mock_service/mock_notifications.sqlite3'))
if not DB_PATH.is_absolute():
    DB_PATH = ROOT / DB_PATH
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
SECRET = os.getenv('MOCK_SHARED_SECRET', 'replace_me_with_another_random_secret')
DB_LOCK = threading.Lock()

def connect():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with DB_LOCK, connect() as db:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS deliveries(
           event_key TEXT PRIMARY KEY, payload TEXT NOT NULL, delivered_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS inbound_attempts(
           event_key TEXT PRIMARY KEY, count INTEGER NOT NULL DEFAULT 0
        );
        INSERT OR IGNORE INTO settings(key,value) VALUES('mode','healthy');
        ''')

def get_mode():
    with DB_LOCK, connect() as db:
        row = db.execute("SELECT value FROM settings WHERE key='mode'").fetchone()
        return row['value'] if row else 'healthy'

def set_mode(mode):
    with DB_LOCK, connect() as db:
        db.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('mode',?)", (mode,))

def record_incoming(event_key):
    with DB_LOCK, connect() as db:
        db.execute('INSERT INTO inbound_attempts(event_key,count) VALUES(?,1) '
                   'ON CONFLICT(event_key) DO UPDATE SET count=count+1', (event_key,))
        return db.execute('SELECT count FROM inbound_attempts WHERE event_key=?', (event_key,)).fetchone()['count']

def save_delivery(event_key, payload):
    with DB_LOCK, connect() as db:
        cur = db.execute('INSERT OR IGNORE INTO deliveries(event_key,payload,delivered_at) VALUES(?,?,?)',
                         (event_key, json.dumps(payload), datetime.now(timezone.utc).isoformat()))
        return cur.rowcount == 1

def delivery_exists(event_key):
    with DB_LOCK, connect() as db:
        return db.execute('SELECT 1 FROM deliveries WHERE event_key=?', (event_key,)).fetchone() is not None

def current_status():
    with DB_LOCK, connect() as db:
        count = db.execute('SELECT COUNT(*) AS n FROM deliveries').fetchone()['n']
        tries = db.execute('SELECT COALESCE(SUM(count),0) AS n FROM inbound_attempts').fetchone()['n']
    return {'mode': get_mode(), 'delivered_unique': count, 'requests_seen': tries}

class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, fmt, *args):
        print('%s %s' % (self.address_string(), fmt % args), flush=True)

    def send_json(self, code, obj):
        data = json.dumps(obj).encode()
        try:
            self.send_response(code)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass  # Expected in timeout simulation.

    def authorized(self):
        if self.headers.get('X-Mock-Secret') != SECRET:
            self.send_json(403, {'error': 'invalid mock shared secret'})
            return False
        return True

    def read_body(self):
        n = int(self.headers.get('Content-Length', '0'))
        if n > 32768:
            raise ValueError('Body too large')
        data = json.loads(self.rfile.read(n)) if n else {}
        if not isinstance(data, dict):
            raise ValueError('Expected JSON object')
        return data

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == '/health':
            return self.send_json(200, {'status': 'ok'})
        if not self.authorized():
            return
        if path == '/status':
            return self.send_json(200, current_status())
        if path == '/deliveries':
            with DB_LOCK, connect() as db:
                rows = db.execute('SELECT * FROM deliveries ORDER BY delivered_at DESC LIMIT 200').fetchall()
            return self.send_json(200, {'deliveries': [{'event_key': r['event_key'],
                'payload': json.loads(r['payload']), 'delivered_at': r['delivered_at']} for r in rows]})
        self.send_json(404, {'error': 'not found'})

    def do_POST(self):
        if not self.authorized():
            return
        path = urlsplit(self.path).path
        try:
            payload = self.read_body()
        except (ValueError, json.JSONDecodeError):
            return self.send_json(400, {'error': 'invalid JSON'})
        if path == '/control':
            mode = payload.get('mode')
            if mode not in ('healthy', 'always_503', 'timeout', 'flaky'):
                return self.send_json(400, {'error': 'invalid mode'})
            set_mode(mode)
            return self.send_json(200, current_status())
        if path != '/notify':
            return self.send_json(404, {'error': 'not found'})
        key = self.headers.get('Idempotency-Key', '')
        if not (3 <= len(key) <= 150) or payload.get('type') not in (
                'REGISTRATION_CONFIRMED', 'WORKSHOP_CANCELLED'):
            return self.send_json(400, {'error': 'invalid event'})
        if delivery_exists(key):
            record_incoming(key)
            return self.send_json(200, {'delivered': True, 'duplicate': True, 'event_key': key})
        attempt = record_incoming(key)
        mode = get_mode()
        if mode == 'always_503' or (mode == 'flaky' and attempt <= 2):
            return self.send_json(503, {'error': 'simulated notification outage', 'attempt': attempt})
        if mode == 'timeout':
            time.sleep(3.0)  # Intentionally longer than HTTP timeout 1.3s.
        inserted = save_delivery(key, payload)
        return self.send_json(200, {'delivered': True, 'duplicate': not inserted, 'event_key': key})

if __name__ == '__main__':
    init_db()
    host = os.environ.get('MOCK_BIND_HOST', '127.0.0.1')
    port = int(os.environ.get('MOCK_PORT', '9100'))
    print(f'Mock notification service on http://{host}:{port} db={DB_PATH}', flush=True)
    ThreadingHTTPServer((host, port), Handler).serve_forever()
