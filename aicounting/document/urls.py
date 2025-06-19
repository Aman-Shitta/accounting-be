from django.urls import path


from document.views import DocumentUploadView, DocumentListView, DocumentGetDataView

urlpatterns = [
    path("upload/", DocumentUploadView.as_view(), name="upload_document"),
    path("list/", DocumentListView.as_view(), name="list_document"),
    path("<str:doc_id>/", DocumentGetDataView.as_view(), name="data_document"),

]
