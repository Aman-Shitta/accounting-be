"""
Create (or update) a platform-staff login.

A platform account is deliberately not a ``FirmMembership`` — it belongs to no
firm, and ``UserProfile.is_platform_staff`` is what gets it into the
cross-firm ``/platform/`` surface instead of a firm's own dashboard.
"""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from v1.identity.models import UserProfile

User = get_user_model()


class Command(BaseCommand):
    help = "Create or promote a platform-staff account."

    def add_arguments(self, parser):
        parser.add_argument("email")
        parser.add_argument(
            "--password",
            help="Set explicitly, or omit to be prompted (never passed on the "
            "command line in a shared shell history otherwise).",
        )

    def handle(self, *args, **options):
        email = options["email"].strip().lower()
        password = options["password"] or self._prompt_password()

        user, created = User.objects.get_or_create(
            username=email, defaults={"email": email, "is_active": True}
        )
        user.email = email
        user.is_active = True
        user.set_password(password)
        user.save()

        profile, _ = UserProfile.objects.get_or_create(user=user)
        profile.is_verified = True
        profile.is_platform_staff = True
        profile.save(update_fields=["is_verified", "is_platform_staff", "updated_at"])

        verb = "Created" if created else "Updated"
        self.stdout.write(self.style.SUCCESS(f"{verb} platform account: {email}"))

    def _prompt_password(self) -> str:
        import getpass

        password = getpass.getpass("Password: ")
        if not password:
            raise CommandError("A password is required.")
        if password != getpass.getpass("Confirm password: "):
            raise CommandError("Passwords did not match.")
        return password
