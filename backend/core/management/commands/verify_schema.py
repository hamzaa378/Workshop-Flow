"""Read-only MySQL acceptance check: all required objects are installed."""
from django.core.management.base import BaseCommand, CommandError
from django.db import connection

EXPECTED = {
    'BASE TABLE': {'accounts','workshops','registrations','notification_outbox',
                   'delivery_attempts','activity_audit'},
    'VIEW': {'v_workshop_metrics','v_notification_queue_summary','v_member_registrations'},
    'TRIGGER': {'trg_registration_guard','trg_registration_outbox','trg_cancel_outbox'},
    'PROCEDURE': {'sp_register_member','sp_cancel_workshop',
                  'sp_repair_missing_cancellation_events'},
    'FUNCTION': {'fn_seats_remaining','fn_retry_delay_seconds'},
}

class Command(BaseCommand):
    help = 'Verify MySQL tables, views, triggers, procedures and functions without changing data.'

    def handle(self, *args, **kwargs):
        found = {k: set() for k in EXPECTED}
        with connection.cursor() as cursor:
            cursor.execute('SELECT DATABASE()')
            self.stdout.write(f'Database: {cursor.fetchone()[0]}')
            cursor.execute('SELECT table_name, table_type FROM information_schema.tables '
                           'WHERE table_schema=DATABASE()')
            for name, kind in cursor.fetchall():
                if kind in found: found[kind].add(name)
            cursor.execute('SELECT trigger_name FROM information_schema.triggers '
                           'WHERE trigger_schema=DATABASE()')
            found['TRIGGER'].update(row[0] for row in cursor.fetchall())
            cursor.execute('SELECT routine_name, routine_type FROM information_schema.routines '
                           'WHERE routine_schema=DATABASE()')
            for name, kind in cursor.fetchall():
                if kind in found: found[kind].add(name)
            cursor.execute('SELECT fn_retry_delay_seconds(3)')
            self.stdout.write(f'Retry backoff example: {cursor.fetchone()[0]} seconds at attempt 3')
        missing_any = False
        for kind, required in EXPECTED.items():
            missing = required - found[kind]
            self.stdout.write(f'{kind}: {len(required - missing)}/{len(required)}  '
                              f'{"PASS" if not missing else "FAIL " + ", ".join(sorted(missing))}')
            missing_any |= bool(missing)
        if missing_any:
            raise CommandError('SQL schema is incomplete. Rerun 01_schema.sql and 02_programmability.sql.')
        self.stdout.write(self.style.SUCCESS('ALL SCHEMA OBJECT CHECKS PASS'))
