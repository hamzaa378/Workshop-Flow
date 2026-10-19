from django.urls import path
from core import api

urlpatterns = [
    path('api/health/', api.health),
    path('api/auth/login/', api.login),
    path('api/me/', api.me),
    path('api/workshops/', api.workshops),
    path('api/workshops/<int:workshop_id>/register/', api.register),
    path('api/workshops/<int:workshop_id>/cancel/', api.cancel),
    path('api/workshops/<int:workshop_id>/registrants/', api.registrants),
    path('api/registrations/mine/', api.my_registrations),
    path('api/outbox/', api.outbox),
    path('api/outbox/<int:event_id>/retry/', api.retry_event),
    path('api/stats/', api.stats),
    path('api/audit/', api.audit),
    path('api/mock/status/', api.mock_status),
    path('api/mock/mode/', api.mock_mode),
    path('api/mock/deliveries/', api.mock_deliveries),
]
