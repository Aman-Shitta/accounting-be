from django.urls import path, include

from .gl_account_views import ClientGLAccountListView

from django.urls import path
from .input_file_views import (
    InputFileListView,
    InputFileCreateView,
    InputFileDetailView,
    AttributeCreateView,
    AttributeListView,
    AttributeBulkDeleteView,
)

# Input Files API URL patterns
input_file_patterns = [
    # Input Files for a specific client
    path('', InputFileListView.as_view(), name='list'),
    path('create/', InputFileCreateView.as_view(), name='create'),
    
    # Specific Input File operations
    path('<int:file_id>/', InputFileDetailView.as_view(), name='detail'),
        
    # Attributes for a specific input file
    path('<int:file_id>/attributes/', AttributeListView.as_view(), name='attribute_list'),
    path('<int:file_id>/attributes/create/', AttributeCreateView.as_view(), name='attribute_create'),
    path('<int:file_id>/attributes/bulk_delete/', AttributeBulkDeleteView.as_view(), name='attribute_bulk_delete'),
]


urlpatterns = [
    path('client/<int:client_id>/accounts/', ClientGLAccountListView.as_view(), name='client_accounts_list'),
    
    # Include input file URLs
    path('clients/<int:client_id>/input_files/', include((input_file_patterns, 'account'), 'input_files')),
]
