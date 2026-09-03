import logging
import os
from datetime import datetime, timedelta

from azure.storage.blob import (
    BlobSasPermissions,
    BlobServiceClient,
    generate_blob_sas,
)
from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import Storage
from django.utils.deconstruct import deconstructible

logger = logging.getLogger(__name__)


@deconstructible
class AzureMediaStorage(Storage):
    """
    Custom Azure Blob Storage backend for media files with customer/client folder structure
    """

    def __init__(self):
        self.account_name = settings.AZURE_ACCOUNT_NAME
        self.account_key = settings.AZURE_ACCOUNT_KEY
        self.container_name = settings.AZURE_CONTAINER_NAME
        self.blob_service_client = BlobServiceClient(
            account_url=f"https://{self.account_name}.blob.core.windows.net",
            credential=self.account_key
        )

    def _get_blob_client(self, name):
        return self.blob_service_client.get_blob_client(
            container=self.container_name,
            blob=name
        )

    def _normalize_name(self, name):
        """
        Normalize file name to ensure proper path formatting for Azure
        """
        if name is None:
            return None
        # Replace backslashes with forward slashes for Azure paths
        return name.replace('\\', '/')

    def _save(self, name, content):
        """
        Save content to Azure Blob Storage
        """
        normalized_name = self._normalize_name(name)
        blob_client = self._get_blob_client(normalized_name)

        # Handle both file-like objects and bytes
        if hasattr(content, 'read'):
            content_data = content.read()
        else:
            content_data = content

        blob_client.upload_blob(content_data, overwrite=True)
        logger.info(f"Successfully uploaded file to Azure: {normalized_name}")
        return normalized_name

    def _open(self, name, mode='rb'):
        """
        Open and retrieve content from Azure Blob Storage
        """
        normalized_name = self._normalize_name(name)
        blob_client = self._get_blob_client(normalized_name)
        blob_data = blob_client.download_blob().readall()
        return ContentFile(blob_data)

    def delete(self, name):
        """
        Delete a file from Azure Blob Storage
        """
        normalized_name = self._normalize_name(name)
        blob_client = self._get_blob_client(normalized_name)
        try:
            blob_client.delete_blob()
            logger.info(
                f"Successfully deleted file from Azure: {normalized_name}")
        except Exception as e:
            logger.error(
                f"Error deleting file from Azure {normalized_name}: {e}")

    def exists(self, name):
        """
        Check if a file exists in Azure Blob Storage
        """
        normalized_name = self._normalize_name(name)
        blob_client = self._get_blob_client(normalized_name)
        try:
            blob_client.get_blob_properties()
            return True
        except Exception:
            return False

    def url(self, name, expire_minutes=60):
        """
        Generate a temporary URL with SAS token
        """
        normalized_name = self._normalize_name(name)
        if not normalized_name:
            return ""
        sas_token = generate_blob_sas(
            account_name=self.account_name,
            container_name=self.container_name,
            blob_name=normalized_name,
            account_key=self.account_key,
            permission=BlobSasPermissions(read=True),
            expiry=datetime.utcnow() + timedelta(minutes=expire_minutes)
        )

        return f"https://{self.account_name}.blob.core.windows.net/{self.container_name}/{normalized_name}?{sas_token}"

    def size(self, name):
        """
        Get the size of a file in Azure Blob Storage
        """
        normalized_name = self._normalize_name(name)
        blob_client = self._get_blob_client(normalized_name)
        return blob_client.get_blob_properties().size

    def get_available_name(self, name, max_length=None):
        """
        Get available name for file upload
        """
        normalized_name = self._normalize_name(name)
        if not self.exists(normalized_name):
            return normalized_name

        # If file exists, append timestamp to make it unique
        from pathlib import Path
        path_obj = Path(normalized_name)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        new_name = f"{path_obj.stem}_{timestamp}{path_obj.suffix}"
        return self._normalize_name(str(path_obj.parent / new_name))

    def listdir(self, path):
        """
        List contents of a directory in Azure Blob Storage
        """
        normalized_path = self._normalize_name(path)
        if normalized_path and not normalized_path.endswith('/'):
            normalized_path += '/'

        container_client = self.blob_service_client.get_container_client(
            self.container_name)
        blobs = container_client.list_blobs(name_starts_with=normalized_path)

        dirs = set()
        files = []

        for blob in blobs:
            relative_path = blob.name[len(normalized_path):]
            if '/' in relative_path:
                # It's a subdirectory
                dirs.add(relative_path.split('/')[0])
            else:
                # It's a file
                files.append(relative_path)

        return list(dirs), files
