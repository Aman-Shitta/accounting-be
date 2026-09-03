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
    - **reviewer** — every client of their firm, so they can be handed any of
      its documents for review
    - **accountant** — only clients explicitly assigned to them

    Nothing here reaches beyond the firm on the membership. A user with
    memberships in several firms sees the union of what each grants.
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

    # Owners and reviewers both see their whole firm; accountants see only what
    # they have been assigned.
    firm_wide_roles = {FirmMembership.Role.OWNER, FirmMembership.Role.REVIEWER}
    firm_ids = [m.firm_id for m in memberships if m.role in firm_wide_roles]
    accountant_ids = [
        m.id for m in memberships if m.role == FirmMembership.Role.ACCOUNTANT
    ]

    condition = models.Q(pk__in=[])
    if firm_ids:
        condition |= models.Q(firm_id__in=firm_ids)
    if accountant_ids:
        condition |= models.Q(assignments__membership_id__in=accountant_ids)

    return Client.objects.filter(is_deleted=False).filter(condition).distinct()


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


def firm_for(user):
    """
    The firm the caller belongs to. Every role has one, reviewers included.

    Raises ``NotFound`` when the user has no active membership — there is
    nothing for them to act on.
    """
    from rest_framework.exceptions import NotFound

    from v1.tenancy.models import FirmMembership

    membership = (
        FirmMembership.objects.filter(user=user, is_active=True)
        .select_related("firm")
        .first()
    )
    if membership is None:
        raise NotFound("You do not belong to a firm.")
    return membership.firm
