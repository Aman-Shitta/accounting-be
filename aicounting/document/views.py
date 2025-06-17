from rest_framework.views import APIView
from rest_framework.parsers import MultiPartParser

from rest_framework import status
from django.conf import settings
from pathlib import Path
from document.models.dim_aic_doc_model import DimAICDocument
from tasks import process_uploaded_document
from aicounting.response import create_api_response
import os
import uuid

class DocumentUploadView(APIView):
    parser_classes = [MultiPartParser]

    def post(self, request, *args, **kwargs):
        uploaded_file = request.FILES.get("file")
        doc_type = request.data.get("doc_type", "generic")

        if not uploaded_file:
            return create_api_response(
                status_code=status.HTTP_400_BAD_REQUEST,

            )
        # ({"error": "No file provided"}, status=status.HTTP_400_BAD_REQUEST)

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
        doc = DimAICDocument.objects.create(
            doc_id=doc_id,
            doc_typ=doc_type,
            file_format=file_ext.strip('.'),
            upload_stat="uploaded",
            input_user=1,
            file_loc=str(saved_path),
        )

        # Trigger celery job
        process_uploaded_document.delay(str(saved_path), doc_id)

        return Response({"message": "File uploaded", "doc_id": doc_id}, status=status.HTTP_202_ACCEPTED)
