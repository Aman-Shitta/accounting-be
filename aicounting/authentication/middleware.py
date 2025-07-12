from django.utils.deprecation import MiddlewareMixin
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.conf import settings
import jwt

import requests
from jose import jwt
from jose.exceptions import JWTError
from django.utils.deprecation import MiddlewareMixin
from django.contrib.auth.models import AnonymousUser
from django.conf import settings

JWKS_URL = f"https://login.microsoftonline.com/{settings.TENANT_ID}/discovery/v2.0/keys"
JWKS = None

def get_azure_jwks():
    global JWKS
    if JWKS is None:
        resp = requests.get(JWKS_URL)
        JWKS = resp.json()
    return JWKS

class JWTAuthMiddleware(MiddlewareMixin):
    def process_request(self, request):
        token = request.META.get('HTTP_AUTHORIZATION', '').split('Bearer ')[-1]
        if token:
            try:
                payload = jwt.decode(token, settings.SECRET_KEY, algorithms=['HS256'])
                UserModel = get_user_model()
                request.user = UserModel.objects.get(id=payload['user_id'])
            except Exception:
                request.user = AnonymousUser()
        else:
            request.user = AnonymousUser()

