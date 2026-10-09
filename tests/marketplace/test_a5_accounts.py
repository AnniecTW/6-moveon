"""A5 password accounts share campus verification state with allauth."""

import re

from django.apps import apps
from django.contrib.auth import authenticate, get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class A5DefaultAccountTests(TestCase):
    def test_default_configuration_allows_signup_verification_login_and_logout(self):
        response = self.client.post("/account/", {
            "mode": "signup", "username": "phase2_student",
            "email": "phase2_student@illinois.edu",
            "password1": "Local-test-password-2026",
            "password2": "Local-test-password-2026",
        })
        self.assertRedirects(response, "/account/verify/", fetch_redirect_response=False)
        user = get_user_model().objects.get(username="phase2_student")
        self.assertNotIn("_auth_user_id", self.client.session)
        code = re.search(r"\b\d{6}\b", mail.outbox[-1].body).group()
        self.client.post("/account/verify/", {"code": code})
        self.assertRedirects(self.client.post("/account/", {
            "mode": "login", "username": user.username,
            "password": "Local-test-password-2026",
        }), "/")
        self.assertEqual(self.client.session["_auth_user_id"], str(user.pk))
        self.assertRedirects(self.client.post("/account/logout/"), "/")
        self.assertNotIn("_auth_user_id", self.client.session)


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
)
class A5SharedVerificationTests(TestCase):
    def email_addresses(self):
        self.assertTrue(apps.is_installed("allauth.account"))
        return apps.get_model("account", "EmailAddress").objects

    def make_student(self, **overrides):
        return get_user_model().objects.create_user(
            username="phase2_student", email="phase2_student@illinois.edu",
            password="Local-test-password-2026", display_name="Phase 2 Student",
            **overrides,
        )

    def login_data(self, **overrides):
        return {
            "mode": "login", "username": "phase2_student",
            "password": "Local-test-password-2026", **overrides,
        }

    def test_signup_and_campus_code_update_the_same_allauth_email(self):
        self.client.post(reverse("account"), {
            "mode": "signup", "username": "phase2_student",
            "email": "PHASE2_STUDENT@ILLINOIS.EDU",
            "password1": "Local-test-password-2026",
            "password2": "Local-test-password-2026",
        })
        user = get_user_model().objects.get(username="phase2_student")
        address = self.email_addresses().get(user=user)
        self.assertEqual(address.email, "phase2_student@illinois.edu")
        self.assertTrue(address.primary)
        self.assertFalse(address.verified)
        code = re.search(r"\b\d{6}\b", mail.outbox[-1].body).group()
        self.client.post(reverse("account_verify"), {"code": code})
        address.refresh_from_db()
        user.refresh_from_db()
        self.assertTrue(address.verified)
        self.assertTrue(user.email_verified)
        self.assertIsNotNone(user.email_verified_at)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_existing_verified_user_gets_a_matching_email_record_on_login(self):
        user = self.make_student(email_verified=True, email_verified_at=timezone.now())
        self.assertRedirects(self.client.post(reverse("account"), self.login_data()), "/")
        address = self.email_addresses().get(user=user)
        self.assertTrue(address.verified)
        self.assertTrue(address.primary)

    def test_email_change_revokes_both_verification_records(self):
        user = self.make_student(email_verified=True, email_verified_at=timezone.now())
        self.client.post(reverse("account"), self.login_data())
        addresses = self.email_addresses()
        user.email = "changed@illinois.edu"
        user.save(update_fields=["email"])
        user.refresh_from_db()
        self.assertFalse(user.email_verified)
        self.assertIsNone(user.email_verified_at)
        self.assertFalse(addresses.filter(user=user, verified=True).exists())
        self.assertEqual(addresses.get(user=user, primary=True).email, "changed@illinois.edu")
        self.assertNotEqual(self.client.get(reverse("seller-listings")).status_code, 200)

    def test_allauth_verified_claim_alone_cannot_grant_campus_login(self):
        user = self.make_student()
        self.email_addresses().create(
            user=user, email=user.email, primary=True, verified=True,
        )
        self.assertRedirects(
            self.client.post(reverse("account"), self.login_data()),
            reverse("account_verify"),
        )
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertFalse(self.email_addresses().get(user=user).verified)

    def test_allauth_backend_cannot_bypass_ambiguous_username_email(self):
        self.email_addresses()
        self.make_student(email_verified=True, email_verified_at=timezone.now())
        get_user_model().objects.create_user(
            username="phase2_student@illinois.edu", email="another@illinois.edu",
            password="Local-test-password-2026", display_name="Another Student",
            email_verified=True, email_verified_at=timezone.now(),
        )
        self.assertIsNone(authenticate(
            username="phase2_student@illinois.edu", password="Local-test-password-2026",
        ))

    def test_allauth_login_uses_campus_verification_before_creating_a_session(self):
        self.email_addresses()
        from allauth.account.utils import perform_login

        user = self.make_student()
        request = self.client.get(reverse("account")).wsgi_request
        response = perform_login(request, user, email_verification="none", redirect_url="/")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "/account/verify/")
        self.assertNotIn("_auth_user_id", request.session)
        self.assertEqual(request.session["pending_verification_user_id"], user.pk)
        self.assertEqual(len(mail.outbox), 1)

    def test_allauth_login_rejects_suspended_and_noncampus_accounts(self):
        self.email_addresses()
        from allauth.account.utils import perform_login

        user = self.make_student(email_verified=True, email_verified_at=timezone.now())
        for updates in (
            {"account_status": "SUSPENDED"},
            {"account_status": "ACTIVE", "email": "outside@gmail.com"},
        ):
            for field, value in updates.items():
                setattr(user, field, value)
            user.save()
            request = self.client.get(reverse("account")).wsgi_request
            response = perform_login(request, user, email_verification="none", redirect_url="/")
            self.assertEqual(response.status_code, 403)
            self.assertNotIn("_auth_user_id", request.session)

    def test_demo_identity_stays_unusable_for_password_login(self):
        demo = get_user_model().objects.create(username="maya", email="maya@example.invalid")
        demo.set_unusable_password()
        demo.save(update_fields=["password"])
        self.client.post(reverse("account"), self.login_data(username="maya"))
        demo.refresh_from_db()
        self.assertFalse(demo.has_usable_password())
        self.assertNotIn("_auth_user_id", self.client.session)
