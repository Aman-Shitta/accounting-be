from pathlib import Path
from django.conf import settings

from rest_framework.views import APIView
from rest_framework.parsers import MultiPartParser

from rest_framework import status, permissions
from django.shortcuts import get_object_or_404

from document.models import FactAICDocLine

from document.serializers import (
    DocumentListSerializer,
    DocumentDataSerializer,
    LineUpdateModelSerializer,
    LineUpdateModelSerializer,
    LineItemCreateSerializer
)

from document.models.dim_aic_doc_model import DimAICDocument
from document.tasks import process_uploaded_document
from aicounting.response import create_api_response



class DocumentUploadView(APIView):
    parser_classes = [MultiPartParser]

    def post(self, request, *args, **kwargs):
        uploaded_file = request.FILES.get("file")
        # doc_type = request.data.get("doc_type", "generic")
        doc_type = "bank_statement"

        if not uploaded_file:
            return create_api_response(
                status_code=status.HTTP_400_BAD_REQUEST,
                message="No file provided",
            )

        # Create destination path
        file_ext = Path(uploaded_file.name).suffix

        from django.contrib.auth import get_user_model
        doc = DimAICDocument(
            doc_typ=doc_type,
            file_format=file_ext.strip('.'),
            upload_stat="uploaded",
            input_user=get_user_model().objects.filter().first(),
        )

        upload_dir = Path(settings.MEDIA_ROOT) / str(doc.doc_id)
        upload_dir.mkdir(parents=True, exist_ok=True)
        saved_path = upload_dir / uploaded_file.name

        with open(saved_path, "wb") as f:
            for chunk in uploaded_file.chunks():
                f.write(chunk)

        doc.file_loc=f"{doc.doc_id}/{str(uploaded_file.name)}"
        doc.save()

        # Trigger celery job
        process_uploaded_document.delay(str(saved_path), doc.doc_id)
        
        doc.upload_stat = "processing"
        doc.save()
        return create_api_response(
            status_code=status.HTTP_202_ACCEPTED,
            message="File uploaded",
            data={
                "doc_id": doc.doc_id,
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

        if not document:
            return create_api_response(
                status_code=status.HTTP_400_BAD_REQUEST,
                message="Document Not present",
            )
        serializer = self.serializer_class(document)

        return create_api_response(
                status_code=status.HTTP_200_OK,
                message="Document Data Fetched",
                data=serializer.data
            )


class LineItemUpdateAPIView(APIView):
    # permission_classes = [permissions.IsAuthenticated]

    def patch(self, request, *args, **kwargs):
        line = get_object_or_404(FactAICDocLine, pk=kwargs.get('line_id'), doc__doc_id=kwargs.get('doc_id'))
        serializer = LineUpdateModelSerializer(line, data=request.data, partial=True)

        if serializer.is_valid():
            result = serializer.save()
            return create_api_response(
                status_code=status.HTTP_200_OK,
                message="Line Item Updated",
                data=result
            )

        return create_api_response(
            status_code=status.HTTP_400_BAD_REQUEST,
            message="Something went wrong",
            data=serializer.errors
        )


class LineItemCreateAPIView(APIView):
    # permission_classes = [permissions.IsAuthenticated]

    def post(self, request, doc_id):
        doc = get_object_or_404(DimAICDocument, doc_id=doc_id)

        serializer = LineItemCreateSerializer(data=request.data, context={"doc": doc})
        if serializer.is_valid():
            result = serializer.save()
            return create_api_response(
                message="Line created successfully",
                data=result,
                status_code=status.HTTP_201_CREATED
            )

        return create_api_response(
            message="Invalid data",
            data= serializer.errors,
            status_code=status.HTTP_400_BAD_REQUEST
        )

