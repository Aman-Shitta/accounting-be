
from datetime import timezone
from django.db import models
from django.contrib.auth import get_user_model

User = get_user_model()


class DimAICReviewer(models.Model):

    system_user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='reviewer_profile',
        verbose_name="System User",
        help_text="Reference to the system user account for this reviewer"
    )
    
    email = models.EmailField(verbose_name="User Email", unique=True)

    verified = models.BooleanField(default=False, verbose_name="Verified")

    azure_id = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        unique=True,
        verbose_name="Azure ID",
        help_text="Azure Active Directory user ID for SSO integration"
    )

    refresher_token = models.TextField(
        null=True,
        blank=True,
        verbose_name="Refresher Token",
        help_text="Azure AD refresher token for SSO integration"
    )

    review_assigned_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Review Assigned At",
        help_text="Timestamp when the reviewer was assigned a review task"
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Created At",
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name="Updated At",
    )

    class Meta:
        verbose_name = "Reviewer"
        verbose_name_plural = "Reviewers"

    @property
    def next_reviewer(self):
        """
        Assign review tasks in a round-robin manner among verified reviewers.
        This method can be called when a new document is ready for review to assign it to the next reviewer in line.
        """
        if not self.verified:
            return None  # Only assign tasks to verified reviewers

        # Get all verified reviewers ordered by the last assigned review time
        verified_reviewers = DimAICReviewer.objects.filter(
            verified=True
        ).order_by('review_assigned_at')

        if not verified_reviewers.exists():
            return None  # No verified reviewers available

        # Get the next reviewer in line (the one with the oldest review assignment)
        next_reviewer = verified_reviewers.first()

        # Update the review assignment timestamp for the selected reviewer
        next_reviewer.review_assigned_at = timezone.now()
        next_reviewer.save()

        return next_reviewer