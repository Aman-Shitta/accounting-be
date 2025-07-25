from django.urls import path
from .views import SSOLoginView, SSOGenerateTokenView

urlpatterns = [
    path('login/', SSOLoginView.as_view(), name='sso-login'),
    path('callback/', SSOGenerateTokenView.as_view(), name='sso-callback'),
]