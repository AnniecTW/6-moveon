"""Exercise allauth's real redirect/state/token/callback flow with fake HTTPS."""

import re
import time
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit

import jwt
import requests
from allauth.account.models import EmailAddress
from allauth.socialaccount.models import SocialAccount, SocialToken
from django.contrib.auth import get_user_model
from django.core import mail
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone


PROVIDERS = {"google": {
    "APP": {"client_id": "oauth-test-client", "secret": "oauth-test-secret", "key": ""},
    "SCOPE": ["profile", "email"],
    "AUTH_PARAMS": {"access_type": "online", "prompt": "select_account"},
    "OAUTH_PKCE_ENABLED": True,
}}


@override_settings(
    GOOGLE_CLIENT_ID="oauth-test-client", GOOGLE_CLIENT_SECRET="oauth-test-secret",
    SOCIALACCOUNT_PROVIDERS=PROVIDERS,
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
)
class GoogleOAuthTests(TestCase):
    def claims(self, **updates):
        return {
            "sub": "student-google-sub", "email": "student@illinois.edu",
            "email_verified": True, "name": "Campus Student",
            "aud": "oauth-test-client", "iss": "https://accounts.google.com",
            "exp": int(time.time()) + 3600, **updates,
        }

    def start(self, **data):
        response = self.client.post(reverse("google_login"), data)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(urlsplit(response.url).netloc, "accounts.google.com")
        return parse_qs(urlsplit(response.url).query)

    def callback(self, claims=None, **start_data):
        params = self.start(**start_data)
        return self.finish(params["state"][0], claims or self.claims())

    def finish(self, state, claims):
        token_response = Mock(status_code=200, headers={"content-type": "application/json"})
        token_response.json.return_value = {
            "access_token": "fake-access-token", "token_type": "Bearer",
            # Google delivers this over server-to-server HTTPS. The mock replaces
            # only that transport; allauth still validates issuer/audience/expiry.
            "id_token": jwt.encode(claims, "oauth-transport-test-signing-key-2026", algorithm="HS256"),
        }
        with patch("requests.sessions.Session.request", return_value=token_response) as exchange:
            response = self.client.get(reverse("google_callback"), {"code": "fake-code", "state": state})
        return response, exchange

    def user(self, *, email="student@illinois.edu", verified=True, **updates):
        return get_user_model().objects.create_user(
            username=email.partition("@")[0], email=email,
            password="Campus-password-2026", display_name="Existing student",
            email_verified=verified, email_verified_at=timezone.now() if verified else None,
            **updates,
        )

    def test_new_user_requires_local_code_then_reuses_same_user(self):
        response, exchange = self.callback(next=reverse("messages"))
        self.assertRedirects(response, reverse("account_verify"))
        user = get_user_model().objects.get(email="student@illinois.edu")
        self.assertFalse(user.has_usable_password())
        self.assertFalse(user.email_verified)
        self.assertFalse(EmailAddress.objects.get(user=user).verified)
        self.assertEqual(SocialAccount.objects.get(user=user).uid, "student-google-sub")
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertEqual(exchange.call_args.kwargs["data"]["code"], "fake-code")
        self.assertTrue(exchange.call_args.kwargs["data"]["code_verifier"])
        code = re.search(r"\b\d{6}\b", mail.outbox[-1].body).group()
        self.client.post(reverse("account_verify"), {"code": code})
        self.assertContains(self.client.get(reverse("account") + "?next=/messages/"), "Campus email verified. Continue with Google")
        response, _ = self.callback(next=reverse("messages"))
        self.assertRedirects(response, reverse("messages"))
        self.assertEqual(self.client.session["_auth_user_id"], str(user.pk))
        self.assertEqual(get_user_model().objects.count(), 1)
        self.assertEqual(SocialAccount.objects.count(), 1)
        self.assertFalse(SocialToken.objects.exists())
        self.client.post(reverse("account_logout"))
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertEqual(self.client.get("/reports/listings.json").status_code, 401)

    def test_authorization_has_pkce_and_standard_callback(self):
        params = self.start()
        self.assertEqual(params["redirect_uri"], ["http://testserver/accounts/google/login/callback/"])
        self.assertEqual(params["code_challenge_method"], ["S256"])
        self.assertTrue(params["code_challenge"][0])
        self.assertEqual(params["client_id"], ["oauth-test-client"])
        self.assertEqual(params["access_type"], ["online"])

    def test_missing_wrong_and_replayed_state_never_exchange_code(self):
        params = self.start()
        for state in (None, "wrong-state"):
            with self.subTest(state=state), patch("requests.sessions.Session.request") as exchange:
                response = self.client.get(reverse("google_callback"), {"code": "code", **({"state": state} if state else {})})
                self.assertRedirects(response, reverse("account"), fetch_redirect_response=False)
                exchange.assert_not_called()
        self.finish(params["state"][0], self.claims())
        with patch("requests.sessions.Session.request") as exchange:
            self.client.get(reverse("google_callback"), {"code": "code", "state": params["state"][0]})
            exchange.assert_not_called()

    def test_cancel_and_provider_failure_give_feedback(self):
        state = self.start()["state"][0]
        response = self.client.get(reverse("google_callback"), {"state": state, "error": "access_denied"})
        self.assertContains(self.client.get(response.url), "cancelled")
        state = self.start()["state"][0]
        with patch("requests.sessions.Session.request", side_effect=requests.RequestException("private failure")):
            response = self.client.get(reverse("google_callback"), {"state": state, "code": "code"})
        page = self.client.get(response.url)
        self.assertContains(page, "could not be completed")
        self.assertNotContains(page, "private failure")
        self.assertFalse(get_user_model().objects.exists())

    def test_reject_invalid_google_claims_before_creating_account(self):
        for updates in (
            {"email": "student@gmail.com"}, {"email": "student@illinois.edu.evil.com"},
            {"email_verified": False}, {"sub": ""}, {"aud": "other-client"},
            {"iss": "https://evil.example"}, {"exp": int(time.time()) - 60},
        ):
            with self.subTest(updates=updates):
                response, _ = self.callback(self.claims(**updates))
                self.assertRedirects(response, reverse("account"), fetch_redirect_response=False)
                self.assertNotIn("_auth_user_id", self.client.session)
                self.assertFalse(get_user_model().objects.exists())

    def test_existing_same_email_does_not_merge_automatically(self):
        user = self.user()
        response, _ = self.callback()
        self.assertContains(self.client.get(response.url), "Log in with your password")
        self.assertFalse(SocialAccount.objects.exists())
        self.assertNotIn("_auth_user_id", self.client.session)
        user.refresh_from_db()
        self.assertIsNone(user.google_subject)

    def test_historical_email_metadata_conflict_has_controlled_feedback(self):
        user = self.user(email="current@illinois.edu")
        EmailAddress.objects.create(user=user, email="student@illinois.edu", verified=False)
        response, _ = self.callback()
        self.assertContains(self.client.get(response.url), "existing account")
        self.assertEqual(get_user_model().objects.count(), 1)
        self.assertFalse(SocialAccount.objects.exists())
        self.assertNotIn("socialaccount_sociallogin", self.client.session)

    def test_different_subject_cannot_reuse_linked_email(self):
        user = self.user(google_subject="student-google-sub")
        SocialAccount.objects.create(user=user, provider="google", uid="student-google-sub")
        response, _ = self.callback(self.claims(sub="another-subject"))
        self.assertContains(self.client.get(response.url), "Log in with your password")
        self.assertEqual(SocialAccount.objects.get().uid, "student-google-sub")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_connect_rejects_second_google_identity_for_same_user(self):
        user = self.user()
        SocialAccount.objects.create(user=user, provider="google", uid="old-google-sub")
        self.client.force_login(user)
        response, _ = self.callback(process="connect")
        self.assertContains(self.client.get(response.url), "different Google identity")
        self.assertEqual(SocialAccount.objects.get().uid, "old-google-sub")

    def test_linked_user_without_local_proof_still_requires_code(self):
        user = self.user(verified=False)
        SocialAccount.objects.create(user=user, provider="google", uid="student-google-sub")
        EmailAddress.objects.create(user=user, email=user.email, verified=True, primary=True)
        response, _ = self.callback()
        self.assertRedirects(response, reverse("account_verify"))
        self.assertFalse(EmailAddress.objects.get(user=user).verified)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_existing_user_explicitly_connects_same_email(self):
        user = self.user()
        self.client.force_login(user)
        self.assertContains(self.client.get(reverse("seller-settings")), "Connect Google")
        response, _ = self.callback(process="connect", next=reverse("seller-settings"))
        self.assertRedirects(response, reverse("seller-settings"))
        self.assertEqual(SocialAccount.objects.get().user_id, user.pk)
        self.assertEqual(get_user_model().objects.count(), 1)
        self.client.post(reverse("account_logout"))
        response, _ = self.callback()
        self.assertRedirects(response, reverse("home"))
        self.assertEqual(self.client.session["_auth_user_id"], str(user.pk))

    def test_connect_requires_qualified_session_and_same_email(self):
        response = self.client.post(reverse("google_login"), {"process": "connect"})
        self.assertEqual(response.status_code, 403)
        user = self.user(verified=False)
        self.client.force_login(user)
        self.assertEqual(self.client.post(reverse("google_login"), {"process": "connect"}).status_code, 403)
        user.email_verified = True
        user.email_verified_at = timezone.now()
        user.save()
        response, _ = self.callback(self.claims(email="other@illinois.edu"), process="connect")
        self.assertContains(self.client.get(response.url), "same campus email")
        self.assertFalse(SocialAccount.objects.exists())

    def test_connect_cannot_take_another_users_identity(self):
        owner = self.user(email="owner@illinois.edu")
        SocialAccount.objects.create(user=owner, provider="google", uid="student-google-sub")
        user = self.user()
        self.client.force_login(user)
        response, _ = self.callback(process="connect")
        self.assertEqual(SocialAccount.objects.get().user_id, owner.pk)
        self.assertEqual(self.client.session["_auth_user_id"], str(user.pk))
        self.assertContains(self.client.get(response.url), "another account")

    def test_legacy_subject_link_is_bridged_without_duplicate_user(self):
        user = self.user(google_subject="student-google-sub")
        response, _ = self.callback()
        self.assertRedirects(response, reverse("home"))
        self.assertEqual(SocialAccount.objects.get().user_id, user.pk)
        self.assertEqual(get_user_model().objects.count(), 1)

    def test_linked_email_change_and_suspended_user_are_rejected(self):
        user = self.user()
        SocialAccount.objects.create(user=user, provider="google", uid="student-google-sub")
        response, _ = self.callback(self.claims(email="changed@illinois.edu"))
        self.assertContains(self.client.get(response.url), "email changed")
        user.account_status = "SUSPENDED"
        user.save()
        response, _ = self.callback()
        self.assertContains(self.client.get(response.url), "unavailable")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_unsafe_next_falls_back_to_home(self):
        user = self.user(google_subject="student-google-sub")
        response, _ = self.callback(next="https://evil.example/steal")
        self.assertRedirects(response, reverse("home"))
        self.assertEqual(self.client.session["_auth_user_id"], str(user.pk))

    def test_oauth_initiation_requires_post_and_csrf(self):
        for name in ("google_login", "account_google"):
            with self.subTest(name=name):
                self.assertEqual(self.client.get(reverse(name)).status_code, 405)
                csrf_client = Client(enforce_csrf_checks=True)
                self.assertEqual(csrf_client.post(reverse(name)).status_code, 403)
        response = self.client.post(reverse("account_google"), {"credential": "old-gis-token"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(urlsplit(response.url).netloc, "accounts.google.com")
        self.assertFalse(get_user_model().objects.exists())

    @override_settings(GOOGLE_CLIENT_ID="", GOOGLE_CLIENT_SECRET="", SOCIALACCOUNT_PROVIDERS={})
    def test_unconfigured_login_and_callback_are_controlled(self):
        for name in ("google_login", "google_callback"):
            response = self.client.post(reverse(name)) if name == "google_login" else self.client.get(reverse(name))
            self.assertContains(self.client.get(response.url), "not configured")
        self.assertNotContains(self.client.get(reverse("account")), "gsi/client")

    def test_login_and_signup_use_server_oauth_buttons(self):
        for query in ("", "?mode=signup"):
            page = self.client.get(reverse("account") + query)
            self.assertContains(page, f'action="{reverse("google_login")}"')
            self.assertNotContains(page, "gsi/client")
            self.assertNotContains(page, "data-google-signin")
            self.assertEqual(page.headers.get("Cross-Origin-Opener-Policy"), "same-origin")
