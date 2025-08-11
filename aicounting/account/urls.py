from django.urls import path, include
from .gl_account_views import ClientGLAccountListView
from .je_template_views import JEFreqListView

from .if_urls import (
    input_file_patterns,
)

from .je_urls import (
    je_template_patterns,
)


from .monthly_accounting_urls import monthly_accounting_url_patterns

urlpatterns = [
    # Account URLS
    path('client/<int:client_id>/accounts/', ClientGLAccountListView.as_view(), name='client_accounts_list'),

    # Include input file URLs
    path('clients/<int:client_id>/input_files/', include((input_file_patterns, 'account'), 'input_files')),
]

urlpatterns += [
    path('frequency/', JEFreqListView.as_view(), name='je_freq_list'),
    
    # Include JE template URLs
    path('clients/<int:client_id>/je_templates/', include(je_template_patterns)),
]

urlpatterns += [
    # Include Accounting URLs
    path('clients/<int:client_id>/accounting/monthly/', include(monthly_accounting_url_patterns)),
    
]
    