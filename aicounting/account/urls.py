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
    path('clients/<int:client_id>/input-files/', InputFileListView.as_view(), name='input-file-list'),
    path('clients/<int:client_id>/input-files/create/', InputFileCreateView.as_view(), name='input-file-create'),
    
    # Specific Input File operations
    path('clients/<int:client_id>/input-files/<int:file_id>/', InputFileDetailView.as_view(), name='input-file-detail'),
        
    # Attributes for a specific input file
    path('clients/<int:client_id>/input-files/<int:file_id>/attributes/', AttributeListView.as_view(), name='attribute-list'),
    path('clients/<int:client_id>/input-files/<int:file_id>/attributes/create/', AttributeCreateView.as_view(), name='attribute-create'),
    path('clients/<int:client_id>/input-files/<int:file_id>/attributes/bulk-delete/', AttributeBulkDeleteView.as_view(), name='attribute-bulk-delete'),
]


urlpatterns = [
    path('client/<int:client_id>/accounts/', ClientGLAccountListView.as_view(), name='client-accounts-list'),
    
    # Include input file URLs
    path('', include(input_file_patterns)),
]
