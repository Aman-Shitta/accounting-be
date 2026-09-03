"""
Tenant scoping.

The single place that decides which clients a user may see. Every list
queryset in the API starts from ``Model.objects.for_user(request.user)``;
nothing re-derives the tenant inline.

The old code branched on ``hasattr(user, 'customer_profile')`` in 177 places
across 14 view modules, and any view that forgot the branch leaked data across
firms.
"""

from django.db import models


def accessible_clients(user):
    """
    Return the ``Client`` queryset this user may see.

    - **owner** — every client of their firm
    - **accountant** — only clients explicitly assigned to them
    - **reviewer** — every client, platform-wide

    Reviewers are deliberately platform-scoped, matching the round-robin the
    product ships today. See ``documentation/02-decisions.md``; this crosses
    firm boundaries and is flagged for review.
    """
    from v1.tenancy.models import Client, FirmMembership

    if not user or not user.is_authenticated:
        return Client.objects.none()

    memberships = list(
        FirmMembership.objects.filter(user=user, is_active=True).only(
            "id", "firm_id", "role"
        )
    )
    if not memberships:
        return Client.objects.none()

    live = Client.objects.filter(is_deleted=False)

    if any(m.role == FirmMembership.Role.REVIEWER for m in memberships):
        return live

    owner_firm_ids = [
        m.firm_id for m in memberships if m.role == FirmMembership.Role.OWNER and m.firm_id
    ]
    accountant_ids = [
        m.id for m in memberships if m.role == FirmMembership.Role.ACCOUNTANT
    ]

    condition = models.Q(pk__in=[])
    if owner_firm_ids:
        condition |= models.Q(firm_id__in=owner_firm_ids)
    if accountant_ids:
        condition |= models.Q(assignments__membership_id__in=accountant_ids)

    return live.filter(condition).distinct()


class TenantScopedQuerySet(models.QuerySet):
    """
    A queryset that can restrict itself to one user's visible clients.

    Subclasses set ``client_lookup`` to the ORM path from this model to
    ``Client`` — ``"client"``, ``"period__client"``, ``"pk"`` on ``Client``
    itself.
    """

    client_lookup = "client"

    def for_user(self, user):
        return self.filter(**{f"{self.client_lookup}__in": accessible_clients(user)})


def tenant_manager(lookup: str):
    """
    Build a manager whose queryset scopes through ``lookup``.

        objects = tenant_manager("period__client")()
    """
    queryset_cls = type(
        "ScopedQuerySet", (TenantScopedQuerySet,), {"client_lookup": lookup}
    )
    return models.Manager.from_queryset(queryset_cls)
