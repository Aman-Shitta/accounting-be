from django.urls import path, include

from .client_views import (
    ClientCreateView,
    ClientListView,
    ClientRetrieveView,
    ClientUpdateView,
    ContactCreateView,
    DocumentUploadView,
    ClientAssignAccountantsView,
    ClientAssignedAccountantsView,
    ClientUnassignAccountantsView,
)

from .accountant_views import (
    AzureAccountantInviteView,
    AccountantListView,
)

from .admin_app.admin_urls import admin_urlpatterns

client_urlpatterns = [
    path("create/", ClientCreateView.as_view(), name="client-create"),
    path("list/", ClientListView.as_view(), name="client-list"),
    path("<int:id>/", ClientRetrieveView.as_view(), name="client-detail"),
    path("<int:id>/update/", ClientUpdateView.as_view(), name="client-update"),
    path("<int:id>/contacts/create/",
         ContactCreateView.as_view(), name="contact-create"),
    # path("<int:id>/documents/upload/", DocumentUploadView.as_view(), name="document-upload"),
    path("<int:id>/accountants/assign/",
         ClientAssignAccountantsView.as_view(), name="client-assign-accountants"),
    path("<int:id>/accountants/", ClientAssignedAccountantsView.as_view(),
         name="client-assigned-accountants"),
    path("<int:id>/accountants/unassign/",
         ClientUnassignAccountantsView.as_view(), name="client-unassign-accountants"),
]

accountant_urlpatterns = [
    path("invite/", AzureAccountantInviteView.as_view(), name="accoiuntant-invite"),
    path("list/", AccountantListView.as_view(), name="accountant-list"),

]

urlpatterns = [
    path('admin/', include((admin_urlpatterns, 'cust_admin_auth'))),
    path("client/", include((client_urlpatterns, "client"))),
    path("accountant/", include((accountant_urlpatterns, "accountant"))),
]
