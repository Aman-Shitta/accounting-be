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
    path('', InputFileListView.as_view(), name='input_file_list'),
    path('create/', InputFileCreateView.as_view(), name='input_file_create'),
    
    # Specific Input File operations
    path('<int:file_id>/', InputFileDetailView.as_view(), name='input_file_detail'),

    # Attributes for a specific input file
    path('<int:file_id>/attributes/', AttributeListView.as_view(), name='attribute_list'),
    path('<int:file_id>/attributes/create/', AttributeCreateView.as_view(), name='attribute_create'),
    path('<int:file_id>/attributes/bulk_delete/', AttributeBulkDeleteView.as_view(), name='attribute_bulk_delete'),
]
