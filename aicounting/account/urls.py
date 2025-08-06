from django.urls import path, include
from .gl_account_views import ClientGLAccountListView

from .if_urls import (
    input_file_patterns,
)

urlpatterns = [
    # Account URLS
    path('client/<int:client_id>/accounts/', ClientGLAccountListView.as_view(), name='client_accounts_list'),

    # Include input file URLs
    path('clients/<int:client_id>/input_files/', include((input_file_patterns, 'account'), 'input_files')),
]
