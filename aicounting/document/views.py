from rest_framework.views import APIView
from rest_framework.parsers import MultiPartParser

from rest_framework import status
from django.conf import settings
from pathlib import Path
from document.models.dim_aic_doc_model import DimAICDocument
from document.tasks import process_uploaded_document
from aicounting.response import create_api_response

import uuid

from document.serializers import (
    DocumentListSerializer,
    DocumentDataSerializer
)


class DocumentUploadView(APIView):
    parser_classes = [MultiPartParser]

    def post(self, request, *args, **kwargs):
        uploaded_file = request.FILES.get("file")
        doc_type = request.data.get("doc_type", "generic")

        if not uploaded_file:
            return create_api_response(
                status_code=status.HTTP_400_BAD_REQUEST,
                message="No file provided",
            )

        # Create destination path
        file_ext = Path(uploaded_file.name).suffix
        doc_id = uuid.uuid4().int >> 64
        
        upload_dir = Path(settings.MEDIA_ROOT) / str(doc_id)
        upload_dir.mkdir(parents=True, exist_ok=True)
        saved_path = upload_dir / uploaded_file.name

        with open(saved_path, "wb") as f:
            for chunk in uploaded_file.chunks():
                f.write(chunk)

        # Save doc meta
        DimAICDocument.objects.create(
            doc_id=doc_id,
            doc_typ=doc_type,
            file_format=file_ext.strip('.'),
            upload_stat="uploaded",
            input_user=1,
            file_loc=str(saved_path),
        )

        # Trigger celery job
        process_uploaded_document.delay(str(saved_path), doc_id)

        return create_api_response(
            status_code=status.HTTP_202_ACCEPTED,
            message="File uploaded",
            data={
                "doc_id": doc_id,
                "status": "processing"
            }
        )


class DocumentListView(APIView):

    """
    API to list documents and processed status
    """

    serializer_class = DocumentListSerializer
    
    def get(self, request, *args, **kwargs):
        queryset = DimAICDocument.objects.filter().order_by("-created_at")
        serializer = self.serializer_class(queryset, many=True)
        return create_api_response(
                status_code=status.HTTP_200_OK,
                message="Document List Fetched",
                data=serializer.data
            )
        

class DocumentGetDataView(APIView):

    """
    API to get the data
    """
    serializer_class = DocumentDataSerializer


    def get_object(self, doc_id):
        return DimAICDocument.objects.filter(doc_id=doc_id).first()
    
    def get(self, request, *args, **kwargs):

        doc_id = kwargs.get("doc_id")
        document = self.get_object(doc_id)

        serializer = self.serializer_class(document)

        return create_api_response(
                status_code=status.HTTP_200_OK,
                message="Document Data Fetched",
                data=serializer.data
            )
     