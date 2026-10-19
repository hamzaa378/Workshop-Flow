import os
import time
from django.core.management.base import BaseCommand
from django.db import DatabaseError, close_old_connections
from core.delivery import work_once

class Command(BaseCommand):
    help = 'Continuously dispatch durable notification outbox events; --once sends one batch.'

    def add_arguments(self, parser):
        parser.add_argument('--once', action='store_true')
        parser.add_argument('--batch', type=int, default=int(os.getenv('NOTIFY_BATCH_SIZE', '20')))
        parser.add_argument('--poll', type=float, default=float(os.getenv('NOTIFY_POLL_INTERVAL', '1.0')))

    def handle(self, *args, **opts):
        batch = max(1, min(opts['batch'], 100))
        timeout = float(os.getenv('NOTIFY_HTTP_TIMEOUT', '1.3'))
        lease = int(os.getenv('NOTIFY_LEASE_SECONDS', '15'))
        if lease <= timeout + 3:
            raise ValueError('NOTIFY_LEASE_SECONDS must exceed timeout by at least 3 seconds.')
        self.stdout.write(f'Notification worker started, batch={batch}, lease={lease}s, timeout={timeout}s')
        try:
            while True:
                try:
                    close_old_connections()
                    n = work_once(batch_size=batch, timeout=timeout, lease_seconds=lease)
                except DatabaseError as exc:
                    if opts['once']:
                        raise
                    self.stderr.write(f'Database temporarily unavailable: {exc.__class__.__name__}; retrying')
                    close_old_connections()
                    time.sleep(max(1.0, opts['poll']))
                    continue
                if n:
                    self.stdout.write(f'Dispatched {n} event(s)')
                if opts['once']:
                    break
                if not n:
                    time.sleep(max(0.2, opts['poll']))
        except KeyboardInterrupt:
            self.stdout.write('Worker stopped; queued events remain in MySQL.')
