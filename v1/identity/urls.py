from django.urls import path

from v1.identity.views import (
    ForgotPasswordView,
    LoginView,
    MemberInviteView,
    RefreshTokenView,
    SetPasswordView,
    WhoAmIView,
)

urlpatterns = [
    path("login/", LoginView.as_view(), name="login"),
    path("refresh/", RefreshTokenView.as_view(), name="token-refresh"),
    path("set-password/", SetPasswordView.as_view(), name="set-password"),
    path("forgot-password/", ForgotPasswordView.as_view(), name="forgot-password"),
    path("me/", WhoAmIView.as_view(), name="whoami"),
    path("invite/", MemberInviteView.as_view(), name="member-invite"),
]
