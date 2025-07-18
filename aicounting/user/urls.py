from django.urls import path, include

from .views import ClientCreateView
from .invite_views import AzureInviteView

client_urlpatterns = [
    path("create/", ClientCreateView.as_view(), name="client-create"),
]

accountant_urlpatterns = [
]

urlpatterns = [
    path('invite/', AzureInviteView.as_view(), name='invite'),
    path("client/", include((client_urlpatterns, "client"))),
    # path("accountant/", include((accountant_urlpatterns, "accountant"))),
]
