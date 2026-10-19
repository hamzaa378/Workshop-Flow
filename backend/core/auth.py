"""Signed, expiring bearer credentials for this local competition demo.

Not a replacement for an enterprise identity provider, login throttling or OAuth.
"""
from functools import wraps
from django.core import signing
from django.http import JsonResponse
from .models import Account

SIGN_SALT = 'gdg-workshops-v1'
TOKEN_LIFETIME_SECONDS = 8 * 60 * 60

class ApiError(Exception):
    def __init__(self, message, status=400):
        self.message = message
        self.status = status
        super().__init__(message)

def issue_token(account):
    return signing.dumps({'uid': account.id}, salt=SIGN_SALT, compress=True)

def resolve_user(request):
    header = request.headers.get('Authorization', '')
    if not header.startswith('Bearer '):
        raise ApiError('A bearer token is required.', 401)
    try:
        body = signing.loads(header[7:], salt=SIGN_SALT, max_age=TOKEN_LIFETIME_SECONDS)
        return Account.objects.get(pk=body['uid'])
    except (signing.BadSignature, signing.SignatureExpired, KeyError, Account.DoesNotExist, TypeError):
        raise ApiError('Invalid or expired session. Log in again.', 401)

def protected(role=None):
    def decorator(func):
        @wraps(func)
        def inner(request, *args, **kwargs):
            try:
                user = resolve_user(request)
                if role and user.role != role:
                    raise ApiError('You do not have permission for this operation.', 403)
                return func(request, user, *args, **kwargs)
            except ApiError as exc:
                return JsonResponse({'error': exc.message}, status=exc.status)
        return inner
    return decorator
