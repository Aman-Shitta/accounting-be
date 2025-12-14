from django.urls import path
from .views import (
    SSOLoginView,
    SSOGenerateTokenView,
    SSORefreshTokenView
)

urlpatterns = [
    path('login/', SSOLoginView.as_view(), name='sso-login'),
    path('callback/', SSOGenerateTokenView.as_view(), name='sso-callback'),
    path('refresh/', SSORefreshTokenView.as_view(), name='sso-refresh'),

]