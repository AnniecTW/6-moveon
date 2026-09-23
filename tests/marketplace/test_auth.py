import re
import io
from contextlib import redirect_stdout
from datetime import timedelta
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from django.test import Client
from django.urls import reverse
from django.utils import timezone


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class AccountTests(TestCase):
    def signup_data(self, **overrides):
        return {
            "mode": "signup", "username": "newstudent",
            "email": "newstudent@illinois.edu",
            "password1": "A-strong-password-2026",
            "password2": "A-strong-password-2026", **overrides,
        }

    def login_data(self, **overrides):
        return {"mode": "login", "username": "newstudent",
                "password": "A-strong-password-2026", **overrides}

    def signup(self):
        response = self.client.post(reverse("account"), self.signup_data())
        self.assertRedirects(response, reverse("account_verify"))
        user = get_user_model().objects.get(username="newstudent")
        self.assertFalse(user.email_verified)
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertEqual(len(mail.outbox), 1)
        return user, re.search(r"\b\d{6}\b", mail.outbox[0].body).group()

    def test_signup_verify_login_logout(self):
        user, code = self.signup()
        self.assertRedirects(self.client.post(reverse("account"), self.login_data()), reverse("account_verify"))
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertRedirects(self.client.post(reverse("account_verify"), {"code": code}), reverse("account"))
        user.refresh_from_db()
        self.assertTrue(user.email_verified)
        self.assertRedirects(self.client.post(reverse("account"), self.login_data()), reverse("home"))
        self.assertEqual(self.client.session["_auth_user_id"], str(user.pk))
        self.assertRedirects(self.client.post(reverse("account_logout")), reverse("home"))
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertEqual(self.client.get(reverse("account_verify")).status_code, 302)

    def test_code_attempt_limit_expiry_resend_and_one_time_use(self):
        user, code = self.signup()
        from marketplace.models import EmailVerification

        challenge = EmailVerification.objects.get(user=user)
        self.assertNotEqual(challenge.code_digest, code)
        self.client.post(reverse("account_verify_resend"))
        self.assertContains(self.client.get(reverse("account_verify")), "Wait 60 seconds")
        self.assertEqual(len(mail.outbox), 1)
        for _ in range(5):
            self.client.post(reverse("account_verify"), {"code": "000000" if code != "000000" else "111111"})
        self.assertContains(self.client.post(reverse("account_verify"), {"code": code}), "new code")
        EmailVerification.objects.filter(user=user).update(sent_at=timezone.now() - timedelta(minutes=2))
        self.client.post(reverse("account_verify_resend"))
        self.assertEqual(len(mail.outbox), 2)
        new_code = re.search(r"\b\d{6}\b", mail.outbox[-1].body).group()
        if new_code != code:
            self.assertContains(self.client.post(reverse("account_verify"), {"code": code}), "invalid")
        EmailVerification.objects.filter(user=user).update(expires_at=timezone.now() - timedelta(seconds=1))
        self.assertContains(self.client.post(reverse("account_verify"), {"code": new_code}), "expired")
        EmailVerification.objects.filter(user=user).update(sent_at=timezone.now() - timedelta(minutes=2))
        self.client.post(reverse("account_verify_resend"))
        final_code = re.search(r"\b\d{6}\b", mail.outbox[-1].body).group()
        self.client.post(reverse("account_verify"), {"code": final_code})
        self.assertFalse(EmailVerification.objects.filter(user=user).exists())
        self.assertEqual(self.client.post(reverse("account_verify"), {"code": final_code}).status_code, 302)

    def test_signup_rejects_invalid_and_duplicate_email(self):
        for email in ("student@gmail.com", "student@illinois.edu.evil.com"):
            with self.subTest(email=email):
                self.assertContains(self.client.post(reverse("account"), self.signup_data(email=email)), "@illinois.edu")
        self.signup()
        self.assertContains(self.client.post(reverse("account"), self.signup_data(username="other")), "already exists")

    def test_signup_rejects_username_email_collision_with_another_account(self):
        self.signup()
        self.assertContains(self.client.post(reverse("account"), self.signup_data(
            username="newstudent@illinois.edu", email="other@illinois.edu",
        )), "already used as a campus email")
        get_user_model().objects.create_user(
            username="reserved@illinois.edu", email="different@illinois.edu",
            password="A-strong-password-2026",
        )
        self.assertContains(self.client.post(reverse("account"), self.signup_data(
            username="other", email="reserved@illinois.edu",
        )), "already used as a username")

    def test_wrong_password_and_blocked_accounts(self):
        user, code = self.signup()
        self.assertContains(self.client.post(reverse("account"), self.login_data(password="wrong")), "correct username or campus email and password")
        self.client.post(reverse("account_verify"), {"code": code})
        for updates in ({"is_active": False}, {"account_status": "SUSPENDED"}, {"email_verified": False}):
            get_user_model().objects.filter(pk=user.pk).update(is_active=True, account_status="ACTIVE", email_verified=True)
            get_user_model().objects.filter(pk=user.pk).update(**updates)
            self.client.post(reverse("account"), self.login_data())
            self.assertNotIn("_auth_user_id", self.client.session)
            self.client.post(reverse("account"), self.login_data(username="newstudent@illinois.edu"))
            self.assertNotIn("_auth_user_id", self.client.session)
        get_user_model().objects.filter(pk=user.pk).update(is_active=True, account_status="ACTIVE", email_verified=True)
        self.client.post(reverse("account"), self.login_data())
        get_user_model().objects.filter(pk=user.pk).update(account_status="SUSPENDED")
        self.assertNotContains(self.client.get(reverse("home")), "newstudent")

    def test_password_reset_new_password_and_invalid_link(self):
        user, code = self.signup()
        self.client.post(reverse("account_verify"), {"code": code})
        self.assertRedirects(self.client.post(reverse("password_reset"), {"email": user.email}), reverse("password_reset_done"))
        self.assertEqual(len(mail.outbox), 2)
        link = re.search(r"https?://[^\s]+", mail.outbox[-1].body).group()
        response = self.client.get(link)
        self.assertEqual(response.status_code, 302)
        response = self.client.post(response.url, {"new_password1": "Even-better-password-2026", "new_password2": "Even-better-password-2026"})
        self.assertRedirects(response, reverse("account") + "?reset=done")
        self.assertFalse(self.client.get(link).context["validlink"])
        self.assertRedirects(self.client.post(reverse("account"), self.login_data(password="Even-better-password-2026")), reverse("home"))

    def test_console_reset_link_opens_when_copied_from_its_own_line(self):
        user, code = self.signup()
        self.client.post(reverse("account_verify"), {"code": code})
        output = io.StringIO()
        with override_settings(EMAIL_BACKEND="marketplace.mail_backends.ReadableConsoleEmailBackend"), redirect_stdout(output):
            self.client.post(
                reverse("password_reset"), {"email": user.email},
                HTTP_HOST="127.0.0.1:8000",
            )
        urls = re.findall(r"^https?://[^\s]+$", output.getvalue(), re.MULTILINE)
        self.assertEqual(len(urls), 1)
        self.assertNotIn("Content-Transfer-Encoding", output.getvalue())
        self.assertFalse(urls[0].endswith("="))
        response = self.client.get(urls[0])
        self.assertEqual(response.status_code, 302)
        self.assertTrue(self.client.get(response.url).context["validlink"])

    def test_email_and_username_can_both_sign_in_with_same_password(self):
        user, code = self.signup()
        self.client.post(reverse("account_verify"), {"code": code})
        self.assertRedirects(self.client.post(reverse("account"), self.login_data(
            username="NEWSTUDENT@ILLINOIS.EDU",
        )), reverse("home"))
        self.assertEqual(self.client.session["_auth_user_id"], str(user.pk))
        self.client.post(reverse("account_logout"))
        self.assertRedirects(self.client.post(reverse("account"), self.login_data()), reverse("home"))

    def test_unverified_email_login_stays_pending_and_wrong_password_fails(self):
        self.signup()
        self.assertRedirects(self.client.post(reverse("account"), self.login_data(
            username="newstudent@illinois.edu",
        )), reverse("account_verify"))
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertEqual(self.client.post(reverse("account"), self.login_data(
            username="newstudent@illinois.edu", password="wrong",
        )).status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_ambiguous_username_email_with_same_password_does_not_sign_in(self):
        user, code = self.signup()
        self.client.post(reverse("account_verify"), {"code": code})
        get_user_model().objects.create_user(
            username="newstudent@illinois.edu", email="other@illinois.edu",
            password="A-strong-password-2026", email_verified=True,
            email_verified_at=timezone.now(),
        )
        self.assertEqual(self.client.post(reverse("account"), self.login_data(
            username="newstudent@illinois.edu",
        )).status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_console_link_with_trailing_encoded_soft_break_still_opens(self):
        user, code = self.signup()
        self.client.post(reverse("account_verify"), {"code": code})
        self.client.post(reverse("password_reset"), {"email": user.email})
        link = re.search(r"https?://[^\s]+", mail.outbox[-1].body).group()
        copied_link = link[:-1] + "%3D/"
        response = self.client.get(copied_link)
        self.assertEqual(response.status_code, 302)
        response = self.client.get(response.url)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(self.client.get(response.url).context["validlink"])
        wrong_link = link[:-3] + "00%3D/"
        self.assertFalse(self.client.get(wrong_link).context["validlink"])

    def test_google_token_requires_local_verification_and_subject_match(self):
        claims = {"sub": "google-sub-1", "email": "newstudent@illinois.edu", "email_verified": True, "hd": "illinois.edu"}
        with override_settings(GOOGLE_CLIENT_ID="test-client"), patch("marketplace.google_auth.verify_google_token", return_value=claims):
            self.assertRedirects(self.client.post(reverse("account_google"), {"credential": "mock-token"}), reverse("account_verify"))
            user = get_user_model().objects.get(email=claims["email"])
            self.assertFalse(user.email_verified)
            self.assertNotIn("_auth_user_id", self.client.session)
            code = re.search(r"\b\d{6}\b", mail.outbox[-1].body).group()
            self.client.post(reverse("account_verify"), {"code": code})
            self.assertRedirects(self.client.post(reverse("account_google"), {"credential": "mock-token"}), reverse("home"))
            self.client.post(reverse("account_logout"))
            claims["sub"] = "different-sub"
            self.assertEqual(self.client.post(reverse("account_google"), {"credential": "mock-token"}).status_code, 200)
            self.assertNotIn("_auth_user_id", self.client.session)

    def test_google_button_page_allows_popup_without_changing_other_pages(self):
        with override_settings(GOOGLE_CLIENT_ID="test-client"):
            for url in (reverse("account"), reverse("account") + "?mode=signup"):
                with self.subTest(url=url):
                    response = self.client.get(url)
                    self.assertEqual(response.headers.get("Cross-Origin-Opener-Policy"), "same-origin-allow-popups")
            self.assertEqual(self.client.get(reverse("home")).headers.get("Cross-Origin-Opener-Policy"), "same-origin")
        with override_settings(GOOGLE_CLIENT_ID=""):
            self.assertEqual(self.client.get(reverse("account")).headers.get("Cross-Origin-Opener-Policy"), "same-origin")

    def test_email_change_revokes_access_and_old_code(self):
        user, code = self.signup()
        self.client.post(reverse("account_verify"), {"code": code})
        user.refresh_from_db()
        user.email = "another@illinois.edu"
        user.save(update_fields=["email"])
        user.refresh_from_db()
        self.assertFalse(user.email_verified)
        self.assertIsNone(user.email_verified_at)
        self.assertRedirects(self.client.post(reverse("account"), self.login_data()), reverse("account_verify"))
        self.assertEqual(mail.outbox[-1].to, ["another@illinois.edu"])
        self.assertContains(self.client.post(reverse("account_verify"), {"code": code}), "invalid")

    def test_legacy_verified_flag_without_proof_requires_code(self):
        get_user_model().objects.create_user(
            username="newstudent", email="newstudent@illinois.edu",
            password="A-strong-password-2026", email_verified=True,
        )
        self.assertRedirects(self.client.post(reverse("account"), self.login_data()), reverse("account_verify"))
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertEqual(len(mail.outbox), 1)

    def test_expired_reset_link_and_safe_return(self):
        user, code = self.signup()
        self.client.post(reverse("account_verify"), {"code": code})
        self.client.post(reverse("password_reset"), {"email": user.email})
        link = re.search(r"https?://[^\s]+", mail.outbox[-1].body).group()
        with override_settings(PASSWORD_RESET_TIMEOUT=-1):
            self.assertFalse(self.client.get(link).context["validlink"])
        self.client.get(reverse("account") + "?next=https://evil.example/steal")
        self.assertRedirects(self.client.post(reverse("account"), self.login_data()), reverse("home"))

    def test_valid_return_path_survives_email_verification(self):
        target = reverse("listing_render")
        self.client.get(reverse("account") + f"?next={target}")
        user, code = self.signup()
        self.client.post(reverse("account_verify"), {"code": code})
        self.assertRedirects(self.client.post(reverse("account"), self.login_data()), target)

    def test_google_rejects_unconfigured_invalid_and_existing_email(self):
        with override_settings(GOOGLE_CLIENT_ID=""):
            self.assertContains(self.client.post(reverse("account_google"), {"credential": "token"}), "not configured")
        with override_settings(GOOGLE_CLIENT_ID="test-client"):
            with patch("marketplace.google_auth.verify_google_token", side_effect=ValueError):
                response = self.client.post(reverse("account_google"), {"credential": "bad"})
                self.assertContains(response, "@illinois.edu")
            get_user_model().objects.create_user(
                username="newstudent", email="newstudent@illinois.edu",
                password="A-strong-password-2026",
            )
            with patch("marketplace.google_auth.verify_google_token", return_value={
                "sub": "sub-2", "email": "newstudent@illinois.edu", "email_verified": True,
            }):
                self.assertContains(self.client.post(reverse("account_google"), {"credential": "mock"}), "already exists")
                self.assertIsNone(get_user_model().objects.get(username="newstudent").google_subject)
        csrf_client = Client(enforce_csrf_checks=True)
        with override_settings(GOOGLE_CLIENT_ID="test-client"):
            self.assertEqual(csrf_client.post(reverse("account_google"), {"credential": "mock"}).status_code, 403)

    def test_mail_failure_does_not_claim_delivery(self):
        with patch("marketplace.email_verification.send_mail", side_effect=OSError("SMTP down")):
            response = self.client.post(reverse("account"), self.signup_data())
        self.assertRedirects(response, reverse("account_verify"), fetch_redirect_response=False)
        self.assertContains(self.client.get(reverse("account_verify")), "could not accept")
        from marketplace.models import EmailVerification
        self.assertFalse(EmailVerification.objects.exists())

    def test_google_verifier_passes_configured_audience_to_library(self):
        from marketplace.google_auth import verify_google_token
        with patch("marketplace.google_auth.id_token.verify_oauth2_token", return_value={"sub": "abc"}) as verify:
            self.assertEqual(verify_google_token("signed-token", "client-id"), {"sub": "abc"})
            self.assertEqual(verify.call_args.args[0], "signed-token")
            self.assertEqual(verify.call_args.args[2], "client-id")


class AdminAccessTests(TestCase):
    def make_admin(self, *, email="developer@example.invalid"):
        return get_user_model().objects.create_superuser(
            username="developer", email=email,
            password="A-strong-password-2026", display_name="Developer",
        )

    def test_noncampus_superuser_can_sign_in_to_admin(self):
        user = self.make_admin()
        self.assertFalse(user.email_verified)

        response = self.client.post(reverse("admin:login"), {
            "username": "developer",
            "password": "A-strong-password-2026",
            "next": reverse("admin:index"),
        })

        self.assertRedirects(response, reverse("admin:index"))
        self.assertEqual(self.client.session["_auth_user_id"], str(user.pk))
        self.assertEqual(self.client.get(reverse("admin:marketplace_user_changelist")).status_code, 200)

    def test_admin_session_has_account_exit_without_student_login_loop(self):
        self.make_admin()
        self.assertTrue(self.client.login(username="developer", password="A-strong-password-2026"))

        response = self.client.get(reverse("account"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Administrator account")
        self.assertContains(response, "Sign out")
        self.assertRedirects(self.client.post(reverse("account_logout")), reverse("home"))
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_admin_session_is_not_shown_as_student_login_on_public_home(self):
        self.make_admin()
        self.assertTrue(self.client.login(username="developer", password="A-strong-password-2026"))

        response = self.client.get(reverse("home"))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'class="account-identity"')
        self.assertContains(response, "Admin session")

    def test_student_login_rejects_admin_without_campus_access(self):
        self.make_admin()

        response = self.client.post(reverse("account"), {
            "mode": "login", "username": "developer",
            "password": "A-strong-password-2026",
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "verified campus access")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_suspended_admin_loses_existing_session_access(self):
        user = self.make_admin()
        self.assertTrue(self.client.login(username="developer", password="A-strong-password-2026"))
        get_user_model().objects.filter(pk=user.pk).update(account_status="SUSPENDED")

        response = self.client.get(reverse("admin:index"))
        self.assertRedirects(response, reverse("admin:login") + "?next=" + reverse("admin:index"))

    def test_admin_user_form_does_not_offer_manual_email_verification(self):
        self.make_admin()
        self.assertTrue(self.client.login(username="developer", password="A-strong-password-2026"))
        user = get_user_model().objects.create_user(
            username="student", email="student@illinois.edu",
            password="A-strong-password-2026", display_name="Student",
        )

        response = self.client.get(reverse("admin:marketplace_user_change", args=[user.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'name="email_verified"')
        self.assertNotContains(response, 'name="email_verified_at_')
        add_response = self.client.get(reverse("admin:marketplace_user_add"))
        self.assertEqual(add_response.status_code, 200)
        self.assertNotContains(add_response, 'name="email_verified"')
        self.assertNotContains(add_response, 'name="email_verified_at_')

        forged_response = self.client.post(reverse("admin:marketplace_user_change", args=[user.pk]), {
            "username": user.username,
            "first_name": "", "last_name": "", "email": user.email,
            "is_active": "on", "display_name": user.display_name,
            "account_status": "ACTIVE",
            "date_joined_0": user.date_joined.strftime("%Y-%m-%d"),
            "date_joined_1": user.date_joined.strftime("%H:%M:%S"),
            "email_verified": "on",
            "email_verified_at_0": timezone.now().strftime("%Y-%m-%d"),
            "email_verified_at_1": timezone.now().strftime("%H:%M:%S"),
            "_save": "Save",
        })
        self.assertEqual(forged_response.status_code, 302)
        user.refresh_from_db()
        self.assertFalse(user.email_verified)
        self.assertIsNone(user.email_verified_at)


@override_settings(ROOT_URLCONF="tests.marketplace.test_auth_urls")
class CampusRouteAccessTests(TestCase):
    def assert_sent_to_account(self, response):
        self.assertEqual(response.status_code, 302)
        target = urlsplit(response["Location"])
        self.assertEqual(target.path, reverse("account"))
        self.assertEqual(parse_qs(target.query)["next"], [reverse("campus_probe")])

    def test_admin_session_cannot_open_student_route(self):
        get_user_model().objects.create_superuser(
            username="developer", email="developer@example.invalid",
            password="A-strong-password-2026", display_name="Developer",
        )
        self.assertTrue(self.client.login(username="developer", password="A-strong-password-2026"))

        self.assert_sent_to_account(self.client.get(reverse("campus_probe")))
        self.assertEqual(self.client.post(reverse("campus_probe")).status_code, 403)
        self.assertContains(self.client.get(reverse("account")), "Administrator account")

    def test_verified_student_can_open_student_route(self):
        get_user_model().objects.create_user(
            username="student", email="student@illinois.edu",
            password="A-strong-password-2026", display_name="Student",
            email_verified=True, email_verified_at=timezone.now(),
        )
        self.assertTrue(self.client.login(username="student", password="A-strong-password-2026"))

        self.assertContains(self.client.get(reverse("campus_probe")), "private student action")
        self.assertContains(self.client.post(reverse("campus_probe")), "private student action")

    def test_guest_cannot_open_student_route(self):
        self.assert_sent_to_account(self.client.get(reverse("campus_probe")))
        self.assertEqual(self.client.post(reverse("campus_probe")).status_code, 403)

    def test_student_returns_to_protected_route_after_login(self):
        get_user_model().objects.create_user(
            username="student", email="student@illinois.edu",
            password="A-strong-password-2026", display_name="Student",
            email_verified=True, email_verified_at=timezone.now(),
        )
        first_response = self.client.get(reverse("campus_probe"))
        self.assert_sent_to_account(first_response)
        self.client.get(first_response["Location"])

        login_response = self.client.post(reverse("account"), {
            "mode": "login", "username": "student",
            "password": "A-strong-password-2026",
        })

        self.assertRedirects(login_response, reverse("campus_probe"))

    def test_revoked_campus_verification_blocks_existing_student_session(self):
        user = get_user_model().objects.create_user(
            username="student", email="student@illinois.edu",
            password="A-strong-password-2026", display_name="Student",
            email_verified=True, email_verified_at=timezone.now(),
        )
        self.assertTrue(self.client.login(username="student", password="A-strong-password-2026"))
        get_user_model().objects.filter(pk=user.pk).update(email_verified=False)

        self.assert_sent_to_account(self.client.get(reverse("campus_probe")))
        self.assertEqual(self.client.post(reverse("campus_probe")).status_code, 403)
