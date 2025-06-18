from django.urls import path


from document.views import DocumentUploadView

urlpatterns = [
    path("upload/", DocumentUploadView.as_view(), name="upload_documrnt"),

]
