"""Pure worker helper tests. Django-dependent module import is skipped if unavailable."""
import os
import sys
from pathlib import Path
import pytest

pytest.importorskip('django')
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
import django
django.setup()
from core.delivery import classify_response, retry_delay

@pytest.mark.parametrize('status,ok', [
    (200, True), (201, True), (204, True), (299, True),
    (300, False), (400, False), (429, False), (500, False), (503, False),
])
def test_http_success_classification(status, ok):
    assert classify_response(status) is ok

@pytest.mark.parametrize('attempt,seconds', [(1,2),(2,4),(3,8),(8,256),(9,300),(25,300)])
def test_exponential_retry_cap(attempt, seconds):
    assert retry_delay(attempt) == seconds
