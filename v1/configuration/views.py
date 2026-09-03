"""Configuration endpoints, including publishing a config version."""

from rest_framework import status
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response

from v1.common.views import ClientNestedViewSet
from v1.configuration.models import (
    ConfigVersion,
    DocumentSource,
    ExtractionField,
    JournalTemplate,
    JournalTemplateLine,
)
from v1.configuration.serializers import (
    ConfigVersionSerializer,
    ConfigVersionSummarySerializer,
    DocumentSourceSerializer,
    ExtractionFieldSerializer,
    JournalTemplateLineSerializer,
    JournalTemplateSerializer,
)
from v1.configuration.services.publish import (
    ConfigurationIncomplete,
    current_version,
    publish_config,
    validate_configuration,
)


class DocumentSourceViewSet(ClientNestedViewSet):
    """A client's configured document sources."""

    queryset = DocumentSource.objects.select_related(
        "ledger_account", "default_offset_account"
    ).prefetch_related("fields")
    serializer_class = DocumentSourceSerializer
    search_fields = ["name"]

    @action(detail=True, methods=["get", "put"], url_path="fields")
    def fields(self, request, client_id=None, pk=None):
        """
        Read or replace the extraction fields on a source.

        PUT replaces the whole set, because the fields are a single
        configuration decision — the extraction schema is built from all of
        them at once.
        """
        source = self.get_object()

        if request.method == "GET":
            return Response(
                ExtractionFieldSerializer(
                    source.fields.all(), many=True
                ).data
            )

        if source.is_transactional:
            raise ValidationError(
                {
                    "document_type": (
                        f"A {source.get_document_type_display()} produces a transaction "
                        f"list, so there is nothing to configure per field."
                    )
                }
            )

        serializer = ExtractionFieldSerializer(data=request.data, many=True)
        serializer.is_valid(raise_exception=True)

        source.fields.all().delete()
        fields = ExtractionField.objects.bulk_create(
            [
                ExtractionField(document_source=source, **item)
                for item in serializer.validated_data
            ]
        )
        return Response(
            ExtractionFieldSerializer(fields, many=True).data,
            status=status.HTTP_200_OK,
        )


class JournalTemplateViewSet(ClientNestedViewSet):
    """A client's journal entry templates."""

    queryset = JournalTemplate.objects.prefetch_related("lines", "sources")
    serializer_class = JournalTemplateSerializer

    @action(detail=True, methods=["get", "put"], url_path="lines")
    def lines(self, request, client_id=None, pk=None):
        """Read or replace a template's lines."""
        template = self.get_object()

        if request.method == "GET":
            return Response(
                JournalTemplateLineSerializer(template.lines.all(), many=True).data
            )

        serializer = JournalTemplateLineSerializer(data=request.data, many=True)
        serializer.is_valid(raise_exception=True)

        template.lines.all().delete()
        lines = JournalTemplateLine.objects.bulk_create(
            [
                JournalTemplateLine(template=template, **item)
                for item in serializer.validated_data
            ]
        )
        return Response(JournalTemplateLineSerializer(lines, many=True).data)


class ConfigVersionViewSet(ClientNestedViewSet):
    """Published configuration versions."""

    queryset = ConfigVersion.objects.select_related("published_by")
    serializer_class = ConfigVersionSerializer
    http_method_names = ["get", "post", "head", "options"]

    def get_serializer_class(self):
        # The payload is large; only send it when one version is asked for.
        if self.action == "list":
            return ConfigVersionSummarySerializer
        return ConfigVersionSerializer

    @action(detail=False, methods=["post"], url_path="publish")
    def publish(self, request, client_id=None):
        """Freeze the client's current configuration as a new version."""
        try:
            version = publish_config(self.client, published_by=request.user)
        except ConfigurationIncomplete as e:
            raise ValidationError({"configuration": e.messages}) from e

        return Response(
            ConfigVersionSerializer(version).data, status=status.HTTP_201_CREATED
        )

    @action(detail=False, methods=["get"], url_path="current")
    def current(self, request, client_id=None):
        version = current_version(self.client)
        if version is None:
            raise NotFound("This client has no published configuration yet.")
        return Response(ConfigVersionSerializer(version).data)

    @action(detail=False, methods=["get"], url_path="check")
    def check(self, request, client_id=None):
        """What, if anything, would stop this configuration being published."""
        problems = validate_configuration(self.client)
        return Response({"publishable": not problems, "problems": problems})
