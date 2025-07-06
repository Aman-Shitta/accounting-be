from django.urls import path


from document.views import (
    DocumentUploadView,
    DocumentListView,
    DocumentGetDataView,

    LineItemUpdateAPIView,
    LineItemCreateAPIView
)


urlpatterns = [
    path("upload/", DocumentUploadView.as_view(), name="upload_document"),
    path("list/", DocumentListView.as_view(), name="list_document"),
    path("<str:doc_id>/", DocumentGetDataView.as_view(), name="data_document"),
    path('<str:doc_id>/line-item/<int:line_id>/', LineItemUpdateAPIView.as_view(), name='line-item-update'),

    path("<str:doc_id>/line-item/add/", LineItemCreateAPIView.as_view(), name="data_document"),
]

