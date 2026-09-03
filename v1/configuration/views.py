"""Document sources, extraction fields, journal templates and config versions."""

from rest_framework import status
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response

from v1.common.views import ClientScopedView, DetailMixin, ListCreateMixin
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

# ---------------------------------------------------------- document sources


class DocumentSourceListView(ListCreateMixin, ClientScopedView):
    queryset = DocumentSource.objects.select_related(
        "ledger_account", "default_offset_account"
    ).prefetch_related("fields")
    serializer_class = DocumentSourceSerializer
    search_fields = ["name"]
    ordering_fields = ["name", "document_type", "created_at"]
    default_ordering = "name"

    def perform_create(self, serializer):
        return serializer.save(client=self.client)


class DocumentSourceDetailView(DetailMixin, ClientScopedView):
    queryset = DocumentSource.objects.select_related(
        "ledger_account", "default_offset_account"
    ).prefetch_related("fields")
    serializer_class = DocumentSourceSerializer


class DocumentSourceFieldsView(ClientScopedView):
    """
    Read or replace the extraction fields on a source.

    PUT replaces the whole set: the extraction schema is built from all of them
    at once, so a partial update has no meaning.
    """

    queryset = DocumentSource.objects.prefetch_related("fields")
    serializer_class = ExtractionFieldSerializer

    def get(self, request, client_id, pk):
        source = self.get_object(pk)
        return Response(ExtractionFieldSerializer(source.fields.all(), many=True).data)

    def put(self, request, client_id, pk):
        source = self.get_object(pk)

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
        return Response(ExtractionFieldSerializer(fields, many=True).data)


# --------------------------------------------------------- journal templates


class JournalTemplateListView(ListCreateMixin, ClientScopedView):
    queryset = JournalTemplate.objects.prefetch_related("lines", "sources")
    serializer_class = JournalTemplateSerializer
    search_fields = ["name", "reference"]
    ordering_fields = ["name", "frequency", "created_at"]
    default_ordering = "name"

    def perform_create(self, serializer):
        return serializer.save(client=self.client)


class JournalTemplateDetailView(DetailMixin, ClientScopedView):
    queryset = JournalTemplate.objects.prefetch_related("lines", "sources")
    serializer_class = JournalTemplateSerializer


class JournalTemplateLinesView(ClientScopedView):
    """Read or replace a template's lines."""

    queryset = JournalTemplate.objects.prefetch_related("lines")
    serializer_class = JournalTemplateLineSerializer

    def get(self, request, client_id, pk):
        template = self.get_object(pk)
        return Response(
            JournalTemplateLineSerializer(template.lines.all(), many=True).data
        )

    def put(self, request, client_id, pk):
        template = self.get_object(pk)

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


# ----------------------------------------------------------- config versions


class ConfigVersionListView(ListCreateMixin, ClientScopedView):
    """Version history. The payload is large, so the list omits it."""

    queryset = ConfigVersion.objects.select_related("published_by")
    serializer_class = ConfigVersionSummarySerializer
    default_ordering = "-version"

    def post(self, request, **kwargs):
        raise NotFound()  # publishing is its own endpoint


class ConfigVersionDetailView(ClientScopedView):
    queryset = ConfigVersion.objects.select_related("published_by")
    serializer_class = ConfigVersionSerializer

    def get(self, request, client_id, pk):
        return Response(ConfigVersionSerializer(self.get_object(pk)).data)


class ConfigPublishView(ClientScopedView):
    """Freeze the client's current configuration as a new version."""

    queryset = ConfigVersion.objects.all()
    serializer_class = ConfigVersionSerializer

    def post(self, request, client_id):
        try:
            version = publish_config(self.client, published_by=request.user)
        except ConfigurationIncomplete as e:
            raise ValidationError({"configuration": e.messages}) from e

        return Response(
            ConfigVersionSerializer(version).data, status=status.HTTP_201_CREATED
        )


class ConfigCurrentView(ClientScopedView):
    queryset = ConfigVersion.objects.all()
    serializer_class = ConfigVersionSerializer

    def get(self, request, client_id):
        version = current_version(self.client)
        if version is None:
            raise NotFound("This client has no published configuration yet.")
        return Response(ConfigVersionSerializer(version).data)


class ConfigCheckView(ClientScopedView):
    """What, if anything, would stop this configuration being published."""

    queryset = ConfigVersion.objects.all()
    serializer_class = ConfigVersionSerializer

    def get(self, request, client_id):
        problems = validate_configuration(self.client)
        return Response({"publishable": not problems, "problems": problems})
