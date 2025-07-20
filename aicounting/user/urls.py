from django.urls import path, include

from .views import (
    ClientCreateView, 
    ClientListView, 
    ClientRetrieveView, 
    ClientUpdateView,
    ContactCreateView,
    DocumentUploadView,
)

from .admin_app.admin_urls import  admin_urlpatterns

client_urlpatterns = [
    path("list/", ClientListView.as_view(), name="client-list"),
    path("create/", ClientCreateView.as_view(), name="client-create"),
    path("<str:assigned_id>/", ClientRetrieveView.as_view(), name="client-detail"),
    path("<str:assigned_id>/update/", ClientUpdateView.as_view(), name="client-update"),
    path("<str:assigned_id>/contacts/create/", ContactCreateView.as_view(), name="contact-create"),
    path("<str:assigned_id>/documents/upload/", DocumentUploadView.as_view(), name="document-upload"),
]

accountant_urlpatterns = [
]

urlpatterns = [
    path('admin/', include((admin_urlpatterns, 'cust_admin_auth'))),
    path("client/", include((client_urlpatterns, "client"))),
    # path("accountant/", include((accountant_urlpatterns, "accountant"))),
]
