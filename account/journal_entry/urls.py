from django.urls import include, path

from account.journal_entry.views import (
    AvailableAttributesView,
    JEFreqListView,
    JETemplateAttributeConfigView,
    JETemplateAttributeDetailView,
    JETemplateCreateView,
    JETemplateDetailView,
    JETemplateListView,
)


# JE Template API URL patterns
je_template_patterns = [

    # JE Templates for a specific client
    path('', JETemplateListView.as_view(), name='je_template_list'),

    # Available attributes for JE Template configuration
    path('available_attributes/', AvailableAttributesView.as_view(),
         name='available_attributes'),

    # Specific JE Template operations [(POST), (GET, PUT, DELETE)]
    path('create/', JETemplateCreateView.as_view(), name='je_template_create'),
    path('<int:template_id>/', JETemplateDetailView.as_view(),
         name='je_template_detail'),

    # JE Template attribute configuration
    path('<int:template_id>/attributes/', JETemplateAttributeConfigView.as_view(),
         name='je_template_attribute_config'),
    path('<int:template_id>/attributes/<int:attr_id>/',
         JETemplateAttributeDetailView.as_view(), name='je_template_attribute_detail'),
]
