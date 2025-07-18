from django.urls import path, include

from .views import ClientCreateView

from .admin_app.admin_urls import  admin_urlpatterns

client_urlpatterns = [
    path("create/", ClientCreateView.as_view(), name="client-create"),
]

accountant_urlpatterns = [
]

urlpatterns = [
    path('admin/', include((admin_urlpatterns, 'cust_admin_auth'))),
    path("client/", include((client_urlpatterns, "client"))),
    # path("accountant/", include((accountant_urlpatterns, "accountant"))),
]
