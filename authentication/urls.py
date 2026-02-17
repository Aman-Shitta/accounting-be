from django.urls import path

from authentication.views import (
    SSOGenerateTokenView,
    SSOLoginView,
    SSORefreshTokenView,
    WhoamiView,
)

urlpatterns = [
    path('login/', SSOLoginView.as_view(), name='sso-login'),
    path('callback/', SSOGenerateTokenView.as_view(), name='sso-callback'),
    path('refresh/', SSORefreshTokenView.as_view(), name='sso-refresh'),
    path('who-am-i/', WhoamiView.as_view(), name='who-am-i'),

]