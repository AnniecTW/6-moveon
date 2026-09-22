from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse


class ListingAccountTests(TestCase):
    def signup_data(self, **overrides):
        return {
            "mode": "signup",
            "username": "newstudent",
            "email": "newstudent@illinois.edu",
            "password1": "A-strong-password-2026",
            "password2": "A-strong-password-2026",
            **overrides,
        }

    def test_guest_profile_opens_account_only_from_main_listing(self):
        home = self.client.get(reverse("home"))
        self.assertContains(home, 'href="/account/"')
        self.assertContains(self.client.get(reverse("account")), "Create account")
        other = self.client.get(reverse("listing_render"))
        self.assertNotContains(other, 'href="/account/"')

    def test_signup_creates_session_and_returns_to_listing(self):
        response = self.client.post(reverse("account"), self.signup_data())
        self.assertRedirects(response, reverse("home"))
        user = get_user_model().objects.get(username="newstudent")
        self.assertEqual(user.email, "newstudent@illinois.edu")
        self.assertTrue(user.check_password("A-strong-password-2026"))
        self.assertEqual(self.client.session["_auth_user_id"], str(user.pk))

    def test_signup_rejects_non_illinois_email(self):
        for email in ("student@gmail.com", "student@illinois.edu.evil.com"):
            with self.subTest(email=email):
                response = self.client.post(
                    reverse("account"), self.signup_data(email=email)
                )
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "@illinois.edu")
                self.assertFalse(get_user_model().objects.filter(username="newstudent").exists())

    def test_signup_rejects_mismatched_passwords(self):
        response = self.client.post(
            reverse("account"), self.signup_data(password2="different-password")
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(get_user_model().objects.filter(username="newstudent").exists())

    def test_login_uses_username_and_returns_to_listing(self):
        get_user_model().objects.create_user(
            username="student", email="student@illinois.edu", password="SecretPass123!"
        )
        response = self.client.post(
            reverse("account"),
            {"mode": "login", "username": "student", "password": "SecretPass123!"},
        )
        self.assertRedirects(response, reverse("home"))
        self.assertContains(self.client.get(reverse("home")), "student")

    def test_bad_login_keeps_guest_on_account_page(self):
        response = self.client.post(
            reverse("account"),
            {"mode": "login", "username": "unknown", "password": "wrong"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Please enter a correct username and password")
        self.assertNotIn("_auth_user_id", self.client.session)
