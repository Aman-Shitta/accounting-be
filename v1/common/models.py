"""Abstract base models shared across the v1 apps."""

from django.db import models
from django.utils import timezone

from v1.common.ids import new_id


class UUIDPrimaryKeyModel(models.Model):
    """
    A UUIDv7 primary key.

    See :mod:`v1.common.ids` for why v7 rather than v4 or a sequence.
    """

    id = models.UUIDField(primary_key=True, default=new_id, editable=False)

    class Meta:
        abstract = True


class TimeStampedModel(UUIDPrimaryKeyModel):
    """A UUIDv7 key plus creation and modification timestamps."""

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class SoftDeleteModel(models.Model):
    """
    Marks a row deleted without removing it.

    Used where downstream rows (extracted transactions, journal entries) must
    survive the parent being removed from the UI.
    """

    is_deleted = models.BooleanField(default=False, db_index=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        abstract = True

    def soft_delete(self, *, save: bool = True) -> None:
        self.is_deleted = True
        self.deleted_at = timezone.now()
        if save:
            self.save(update_fields=["is_deleted", "deleted_at"])

    def restore(self, *, save: bool = True) -> None:
        self.is_deleted = False
        self.deleted_at = None
        if save:
            self.save(update_fields=["is_deleted", "deleted_at"])
