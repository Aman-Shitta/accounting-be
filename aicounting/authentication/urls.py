from django.urls import path
from .views import SSOLoginView, SSOCallbackView

urlpatterns = [
    path('login/', SSOLoginView.as_view(), name='sso-login'),
    path('callback/', SSOCallbackView.as_view(), name='sso-callback'),
]