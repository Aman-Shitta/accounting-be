"""Invite, set password, sign in, refresh, reset."""

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from v1.identity import services
from v1.identity.models import PasswordSetToken
from v1.tenancy.models import Firm, FirmMembership
from v1.tests.conftest import PASSWORD, api_client_for, make_user

User = get_user_model()

pytestmark = pytest.mark.django_db

LOGIN = "/api/v1/auth/login/"
REFRESH = "/api/v1/auth/refresh/"
SET_PASSWORD = "/api/v1/auth/set-password/"
FORGOT = "/api/v1/auth/forgot-password/"
ME = "/api/v1/auth/me/"


def test_invite_creates_inactive_user_and_emails_a_link(api, mailoutbox):
    firm = Firm.objects.create(name="Beans & Co")

    membership, raw_token = services.invite_member(
        email="New.Hire@Example.com", role=FirmMembership.Role.ACCOUNTANT, firm=firm
    )

    user = membership.user
    assert user.email == "new.hire@example.com", "email should be normalised"
    assert user.is_active is False, "an invitee cannot sign in before setting a password"
    assert membership.role == FirmMembership.Role.ACCOUNTANT

    assert len(mailoutbox) == 1
    assert raw_token in mailoutbox[0].body


def test_full_invite_to_signed_in_flow(api):
    firm = Firm.objects.create(name="Beans & Co")
    _, raw_token = services.invite_member(
        email="hire@example.com", role=FirmMembership.Role.ACCOUNTANT, firm=firm
    )

    response = api.post(
        SET_PASSWORD, {"token": raw_token, "password": PASSWORD}, format="json"
    )
    assert response.status_code == 200
    assert "access" in response.data["data"]

    user = User.objects.get(email="hire@example.com")
    assert user.is_active is True
    assert user.profile.is_verified is True

    login = api.post(LOGIN, {"email": "hire@example.com", "password": PASSWORD}, format="json")
    assert login.status_code == 200
    assert set(login.data["data"]) == {"access", "refresh"}


def test_a_token_works_only_once(api):
    firm = Firm.objects.create(name="Beans & Co")
    _, raw_token = services.invite_member(
        email="hire@example.com", role=FirmMembership.Role.ACCOUNTANT, firm=firm
    )

    first = api.post(SET_PASSWORD, {"token": raw_token, "password": PASSWORD}, format="json")
    assert first.status_code == 200

    second = api.post(
        SET_PASSWORD, {"token": raw_token, "password": "another-long-password"}, format="json"
    )
    assert second.status_code == 400


def test_an_expired_token_is_rejected(api):
    user = make_user("stale@example.com", active=False)
    token, raw_token = PasswordSetToken.issue(user, PasswordSetToken.Purpose.INVITE)

    token.expires_at = timezone.now() - timezone.timedelta(minutes=1)
    token.save(update_fields=["expires_at"])

    response = api.post(SET_PASSWORD, {"token": raw_token, "password": PASSWORD}, format="json")
    assert response.status_code == 400
    assert User.objects.get(pk=user.pk).is_active is False


def test_issuing_a_new_token_invalidates_the_previous_one(api):
    user = make_user("resend@example.com", active=False)
    _, first_token = PasswordSetToken.issue(user, PasswordSetToken.Purpose.INVITE)
    _, second_token = PasswordSetToken.issue(user, PasswordSetToken.Purpose.INVITE)

    assert api.post(
        SET_PASSWORD, {"token": first_token, "password": PASSWORD}, format="json"
    ).status_code == 400
    assert api.post(
        SET_PASSWORD, {"token": second_token, "password": PASSWORD}, format="json"
    ).status_code == 200


def test_the_raw_token_is_never_stored(api):
    user = make_user("hash@example.com", active=False)
    token, raw_token = PasswordSetToken.issue(user, PasswordSetToken.Purpose.INVITE)

    assert token.token_hash != raw_token
    assert not PasswordSetToken.objects.filter(token_hash=raw_token).exists()


def test_a_weak_password_is_rejected(api):
    firm = Firm.objects.create(name="Beans & Co")
    _, raw_token = services.invite_member(
        email="hire@example.com", role=FirmMembership.Role.ACCOUNTANT, firm=firm
    )

    response = api.post(SET_PASSWORD, {"token": raw_token, "password": "12345"}, format="json")
    assert response.status_code == 400
    assert "password" in response.data["errors"]


def test_login_failures_do_not_distinguish_unknown_from_wrong(api):
    make_user("real@example.com")

    unknown = api.post(LOGIN, {"email": "ghost@example.com", "password": PASSWORD}, format="json")
    wrong = api.post(LOGIN, {"email": "real@example.com", "password": "nope"}, format="json")

    assert unknown.status_code == wrong.status_code == 400
    assert unknown.data["errors"] == wrong.data["errors"]


def test_an_inactive_user_cannot_sign_in(api):
    make_user("pending@example.com", active=False)
    assert api.post(
        LOGIN, {"email": "pending@example.com", "password": PASSWORD}, format="json"
    ).status_code == 400


def test_refresh_returns_a_new_access_token(api):
    make_user("refresh@example.com")
    login = api.post(LOGIN, {"email": "refresh@example.com", "password": PASSWORD}, format="json")

    response = api.post(REFRESH, {"refresh": login.data["data"]["refresh"]}, format="json")
    assert response.status_code == 200
    assert "access" in response.data["data"]


def test_a_garbage_refresh_token_is_rejected(api):
    assert api.post(REFRESH, {"refresh": "not-a-token"}, format="json").status_code == 401


def test_forgot_password_answers_the_same_either_way(api, mailoutbox):
    make_user("known@example.com")

    known = api.post(FORGOT, {"email": "known@example.com"}, format="json")
    unknown = api.post(FORGOT, {"email": "nobody@example.com"}, format="json")

    assert known.status_code == unknown.status_code == 200
    assert known.data["message"] == unknown.data["message"]
    assert len(mailoutbox) == 1, "only the real account gets an email"


def test_whoami_reports_roles_and_reachable_clients(two_firms):
    owner = two_firms["a"]["owner"]

    response = api_client_for(owner).get(ME)
    assert response.status_code == 200

    data = response.data["data"]
    assert data["email"] == owner.email
    assert data["client_count"] == 2
    assert [m["role"] for m in data["memberships"]] == [FirmMembership.Role.OWNER]


def test_whoami_needs_a_token(api):
    assert api.get(ME).status_code == 401


def test_reviewers_are_invited_without_a_firm():
    membership, _ = services.invite_member(
        email="rev@example.com", role=FirmMembership.Role.REVIEWER
    )
    assert membership.firm is None


def test_a_non_reviewer_invite_requires_a_firm():
    with pytest.raises(services.InviteError):
        services.invite_member(
            email="nofirm@example.com", role=FirmMembership.Role.ACCOUNTANT
        )


def test_inviting_the_same_person_twice_is_refused():
    firm = Firm.objects.create(name="Beans & Co")
    services.invite_member(
        email="dupe@example.com", role=FirmMembership.Role.ACCOUNTANT, firm=firm
    )

    with pytest.raises(services.InviteError):
        services.invite_member(
            email="dupe@example.com", role=FirmMembership.Role.ACCOUNTANT, firm=firm
        )


def test_credential_endpoints_are_throttled(api):
    """Guessing at set-password tokens is rate limited (5/min)."""
    statuses = [
        api.post(
            SET_PASSWORD, {"token": f"guess-{i}", "password": PASSWORD}, format="json"
        ).status_code
        for i in range(7)
    ]

    assert statuses[:5] == [400] * 5, "the first five attempts are answered normally"
    assert statuses[5:] == [429, 429], "further attempts are throttled"
