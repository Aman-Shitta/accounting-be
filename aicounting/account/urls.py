from django.urls import path, include
from .views import AccountListView
from .gl_account_views import ClientGLAccountListView
from .input_file_views import (
    InputFileListView,
    InputFileCreateView,
    InputFileDetailView,
    AttributeCreateView,
    AttributeListView,
    AttributeBulkDeleteView,
)
from .je_template_views import (
    JETemplateListView,
    JETemplateCreateView,
    JETemplateDetailView,
    AvailableAttributesView,
    JETemplateAttributeConfigView,
    JETemplateAttributeDetailView,
    JEFreqListView,
)

# Input Files API URL patterns
input_file_patterns = [
    # Input Files for a specific client
    path('input_files/', InputFileListView.as_view(), name='input_file_list'),
    path('input_files/create/', InputFileCreateView.as_view(), name='input_file_create'),
    
    # Specific Input File operations
    path('input_files/<int:file_id>/', InputFileDetailView.as_view(), name='input_file_detail'),
        
    # Attributes for a specific input file
    path('input_files/<int:file_id>/attributes/', AttributeListView.as_view(), name='attribute_list'),
    path('input_files/<int:file_id>/attributes/create/', AttributeCreateView.as_view(), name='attribute_create'),
    path('input_files/<int:file_id>/attributes/bulk_delete/', AttributeBulkDeleteView.as_view(), name='attribute_bulk_delete'),
]

# JE Template API URL patterns  
je_template_patterns = [

    # JE Templates for a specific client
    path('je_templates/', JETemplateListView.as_view(), name='je_template_list'),
    path('je_templates/create/', JETemplateCreateView.as_view(), name='je_template_create'),
    
    # Available attributes for JE Template configuration
    path('je_templates/available_attributes/', AvailableAttributesView.as_view(), name='available_attributes'),
    
    # Specific JE Template operations
    path('je_templates/<int:template_id>/', JETemplateDetailView.as_view(), name='je_template_detail'),
    
    # JE Template attribute configuration
    path('je_templates/<int:template_id>/attributes/', JETemplateAttributeConfigView.as_view(), name='je_template_attribute_config'),
    path('je_templates/<int:template_id>/attributes/<int:attr_id>/', JETemplateAttributeDetailView.as_view(), name='je_template_attribute_detail'),
]


urlpatterns = [
    path('client/<int:client_id>/accounts/', AccountListView.as_view(), name='client_accounts_list'),
    
    # Include input file URLs
    path('clients/<int:client_id>/', include(input_file_patterns)),
    
    # Include JE template URLs
    path('clients/<int:client_id>/', include(je_template_patterns)),


    # Account URLS
    path('frequency/', JEFreqListView.as_view(), name='je_freq_list'),
]
