from django.urls import path, include
from .gl_account_views import ClientGLAccountListView

from .je_template_views import (
    JETemplateListView,
    JETemplateCreateView,
    JETemplateDetailView,
    AvailableAttributesView,
    JETemplateAttributeConfigView,
    JETemplateAttributeDetailView,
    JEFreqListView,
)


# JE Template API URL patterns  
je_template_patterns = [
    
    path('frequency/', JEFreqListView.as_view(), name='je_freq_list'),
    
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