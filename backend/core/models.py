"""ORM mapping for the versioned MySQL schema. Tables are created using sql/*.sql."""
from django.db import models

class Account(models.Model):
    full_name = models.CharField(max_length=120)
    email = models.EmailField(unique=True)
    role = models.CharField(max_length=12)
    password_hash = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        managed = False
        db_table = 'accounts'

class Workshop(models.Model):
    created_by = models.ForeignKey(Account, on_delete=models.DO_NOTHING, db_column='created_by_id')
    title = models.CharField(max_length=180)
    description = models.TextField()
    starts_at = models.DateTimeField()
    capacity = models.PositiveIntegerField(null=True)
    status = models.CharField(max_length=10, default='OPEN')
    cancelled_at = models.DateTimeField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    class Meta:
        managed = False
        db_table = 'workshops'

class Registration(models.Model):
    workshop = models.ForeignKey(Workshop, on_delete=models.DO_NOTHING)
    member = models.ForeignKey(Account, on_delete=models.DO_NOTHING)
    registered_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        managed = False
        db_table = 'registrations'

class NotificationOutbox(models.Model):
    event_key = models.CharField(max_length=150, unique=True)
    event_type = models.CharField(max_length=32)
    workshop = models.ForeignKey(Workshop, on_delete=models.DO_NOTHING)
    registration = models.ForeignKey(Registration, on_delete=models.DO_NOTHING)
    member = models.ForeignKey(Account, on_delete=models.DO_NOTHING)
    payload = models.JSONField()
    status = models.CharField(max_length=12)
    attempts = models.PositiveIntegerField()
    next_attempt_at = models.DateTimeField()
    lease_until = models.DateTimeField(null=True)
    claimed_by = models.CharField(max_length=100, null=True)
    delivered_at = models.DateTimeField(null=True)
    last_http_status = models.PositiveSmallIntegerField(null=True)
    last_error = models.TextField(null=True)
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField()
    class Meta:
        managed = False
        db_table = 'notification_outbox'

class DeliveryAttempt(models.Model):
    outbox = models.ForeignKey(NotificationOutbox, on_delete=models.DO_NOTHING)
    attempt_number = models.PositiveIntegerField()
    outcome = models.CharField(max_length=20)
    http_status = models.PositiveSmallIntegerField(null=True)
    latency_ms = models.PositiveIntegerField()
    error_message = models.CharField(max_length=500)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        managed = False
        db_table = 'delivery_attempts'

class ActivityAudit(models.Model):
    actor = models.ForeignKey(Account, null=True, on_delete=models.DO_NOTHING)
    action = models.CharField(max_length=100)
    entity_type = models.CharField(max_length=60)
    entity_id = models.PositiveBigIntegerField()
    details = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        managed = False
        db_table = 'activity_audit'
