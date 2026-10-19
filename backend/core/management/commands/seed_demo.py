import os
from datetime import timedelta
from django.contrib.auth.hashers import make_password
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from core.models import Account, Workshop

class Command(BaseCommand):
    help = 'Create local demo organizer, members and workshop; safe to rerun.'

    def add_arguments(self, parser):
        parser.add_argument('--allow-insecure-demo', action='store_true')

    def handle(self, *args, **opts):
        if os.getenv('DJANGO_DEBUG', '').lower() != 'true' and not opts['allow_insecure_demo']:
            raise CommandError('Demo accounts with shared passwords require DJANGO_DEBUG=true.')
        people = [('Organizer Demo', 'organizer@demo.local', 'ORGANIZER'),
                  ('Alex Member', 'alex@demo.local', 'MEMBER'),
                  ('Sam Member', 'sam@demo.local', 'MEMBER')]
        for full_name, email, role in people:
            obj, created = Account.objects.get_or_create(
                email=email, defaults={'full_name': full_name, 'role': role,
                                       'password_hash': make_password('Demo@12345')})
            self.stdout.write(f'{"CREATED" if created else "EXISTS "} {obj.email} ({role})')
        organizer = Account.objects.get(email='organizer@demo.local')
        if not Workshop.objects.filter(created_by=organizer, title='GDG Backend Reliability Workshop').exists():
            Workshop.objects.create(created_by=organizer, title='GDG Backend Reliability Workshop',
                                    description='Test durable registration and recovery from mock HTTP failures.',
                                    starts_at=timezone.now() + timedelta(days=7), capacity=25,
                                    status='OPEN')
            self.stdout.write('CREATED sample workshop')
        self.stdout.write('Local-only password for all accounts: Demo@12345')
