"""
API view bases.

Everything is an ``APIView`` — explicit methods, explicit URLs, no router
magic. The bases here carry the two things every endpoint needs: the response
envelope, and tenant scoping resolved once rather than re-derived per view.
"""

from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.exceptions import NotFound
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from v1.common.envelope import EnvelopeMixin
from v1.common.pagination import paginate
from v1.common.permissions import IsFirmMemberOrReviewer
from v1.common.querysets import accessible_clients


class BaseAPIView(EnvelopeMixin, APIView):
    """Authenticated, enveloped. The root of every view in the API."""

    permission_classes = [IsAuthenticated, IsFirmMemberOrReviewer]


class TenantScopedView(BaseAPIView):
    """
    A view over a model whose rows belong to a client.

    ``queryset`` is scoped through the model's own manager, so a subclass
    cannot forget to restrict it.
    """

    queryset = None
    serializer_class = None

    def get_queryset(self):
        assert self.queryset is not None, f"{type(self).__name__} needs a queryset"
        return self.queryset.for_user(self.request.user)

    def get_object(self, pk):
        return get_object_or_404(self.get_queryset(), pk=pk)

    def serialize(self, instance, many=False, **kwargs):
        return self.serializer_class(
            instance, many=many, context=self.get_serializer_context(), **kwargs
        ).data

    def get_serializer_context(self):
        return {"request": self.request, "view": self}


class FirmScopedView(BaseAPIView):
    """
    A view over a model scoped to a firm directly, not through a client.

    Provides the same ``serialize``/``get_object``/context machinery as
    ``TenantScopedView``, without assuming the queryset is a
    ``TenantScopedQuerySet`` keyed off ``Client`` — a firm-level resource
    (document categories, say) has no client to key off.
    """

    queryset = None
    serializer_class = None

    def get_queryset(self):
        assert self.queryset is not None, f"{type(self).__name__} needs a queryset"
        return self.queryset

    def get_object(self, pk):
        return get_object_or_404(self.get_queryset(), pk=pk)

    def serialize(self, instance, many=False, **kwargs):
        return self.serializer_class(
            instance, many=many, context=self.get_serializer_context(), **kwargs
        ).data

    def get_serializer_context(self):
        return {"request": self.request, "view": self}


class ClientScopedView(TenantScopedView):
    """
    A view under ``/clients/{client_id}/``.

    The client is resolved once, through the caller's visible set. One outside
    that set is reported as missing rather than forbidden, so existence does
    not leak across firms.
    """

    client_field = "client"

    def initial(self, request, *args, **kwargs):
        """
        Resolve the client before dispatching.

        Doing it lazily would let a POST fail serializer validation first,
        answering 400 for a client the caller cannot see — which confirms the
        id exists.
        """
        super().initial(request, *args, **kwargs)
        _ = self.client

    @property
    def client(self):
        if not hasattr(self, "_client"):
            client = (
                accessible_clients(self.request.user)
                .filter(pk=self.kwargs["client_id"])
                .first()
            )
            if client is None:
                raise NotFound("No such client.")
            self._client = client
        return self._client

    def get_queryset(self):
        return super().get_queryset().filter(**{self.client_field: self.client})


# ---------------------------------------------------------------- mixins


class ListCreateMixin:
    """
    GET a page of rows, POST a new one.

    Search and ordering come from ``search_fields`` / ``ordering_fields``;
    anything not named there is ignored rather than passed to the ORM.
    """

    search_fields: list[str] = []
    ordering_fields: list[str] = []
    default_ordering: str | None = None

    def filter_queryset(self, queryset):
        params = self.request.query_params

        search = params.get("search", "").strip()
        if search and self.search_fields:
            from django.db.models import Q

            condition = Q()
            for field in self.search_fields:
                condition |= Q(**{f"{field}__icontains": search})
            queryset = queryset.filter(condition)

        ordering = params.get("ordering", "").strip()
        if ordering and ordering.lstrip("-") in self.ordering_fields:
            queryset = queryset.order_by(ordering)
        elif self.default_ordering:
            queryset = queryset.order_by(self.default_ordering)

        return queryset

    def get(self, request, **_kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page, meta = paginate(queryset, request)
        return Response({**meta, "results": self.serialize(page, many=True)})

    def post(self, request, **_kwargs):
        serializer = self.serializer_class(
            data=request.data, context=self.get_serializer_context()
        )
        serializer.is_valid(raise_exception=True)
        instance = self.perform_create(serializer)
        return Response(
            self.serialize(instance), status=status.HTTP_201_CREATED
        )

    def perform_create(self, serializer):
        return serializer.save()


class DetailMixin:
    """GET one row, PATCH it, DELETE it."""

    def get(self, request, pk, **_kwargs):
        return Response(self.serialize(self.get_object(pk)))

    def patch(self, request, pk, **_kwargs):
        instance = self.get_object(pk)
        serializer = self.serializer_class(
            instance,
            data=request.data,
            partial=True,
            context=self.get_serializer_context(),
        )
        serializer.is_valid(raise_exception=True)
        return Response(self.serialize(serializer.save()))

    def delete(self, request, pk, **_kwargs):
        self.perform_destroy(self.get_object(pk))
        return Response(status=status.HTTP_204_NO_CONTENT)

    def perform_destroy(self, instance):
        instance.delete()
