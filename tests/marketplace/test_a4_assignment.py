from datetime import datetime, timezone as datetime_timezone
from io import BytesIO, StringIO
from hashlib import sha256
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings, tag
from django.urls import reverse
from PIL import Image

from marketplace.models import EmailVerification, ItemCategory, ItemType, Listing, Transaction, User


@override_settings(A4_ASSIGNMENT_MODE=True, A4_DEMO_USERNAME="maya")
@tag("a4")
class A4AnonymousChartsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.demo = User.objects.create_user(
            username="maya", email="maya@example.invalid", display_name="Maya"
        )
        other = User.objects.create_user(
            username="other", email="other@example.invalid", display_name="Other"
        )
        category = ItemCategory.objects.create(category_name="Demo Furniture")
        kind = ItemType.objects.create(category=category, item_type_name="Chair")
        for seller, buyer, title, price, day in [
            (other, cls.demo, "Demo purchase", 40, 1),
            (cls.demo, other, "Demo sale", 18, 2),
        ]:
            listing = Listing.objects.create(
                seller=seller, item_type=kind, title=title, listing_price=price,
                condition="GOOD", fulfillment_option="PICKUP", status="SOLD",
            )
            Transaction.objects.create(
                listing=listing, seller=seller, buyer=buyer, agreed_price=price,
                status="COMPLETED",
                completed_at=datetime(2026, 9, day, 12, tzinfo=datetime_timezone.utc),
            )

    def test_chart_page_and_home_work_without_account_entry(self):
        response = self.client.get("/charts/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-vega-spec=', count=3)
        self.assertContains(response, "Fictional demo data")
        home = self.client.get(reverse("home"))
        self.assertContains(home, 'href="/charts/"')
        self.assertNotContains(home, 'href="/account/"')

    def test_anonymous_chart_api_uses_demo_transactions(self):
        response = self.client.get(reverse("profile-earned-spent-data"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [
            {"activity": "Total Spent", "amount": 40.0},
            {"activity": "Total Earned", "amount": 18.0},
        ])
        self.assertFalse(response.wsgi_request.user.is_authenticated)
        self.assertEqual(response["Access-Control-Allow-Origin"], "https://vega.github.io")
        timeline = self.client.get(reverse("profile-earned-spent-timeline-data"))
        self.assertEqual(timeline.status_code, 200)
        self.assertEqual(timeline.json()[-1]["amount"], 18.0)

    def test_specs_keep_api_urls_and_pngs_render_without_a_second_web_worker(self):
        for spec_name, png_name in [
            ("vega-earned-spent-spec", "vega-earned-spent-png"),
            ("vega-earned-spent-timeline-spec", "vega-earned-spent-timeline-png"),
        ]:
            with self.subTest(spec=spec_name):
                spec_response = self.client.get(reverse(spec_name))
                self.assertEqual(spec_response.status_code, 200)
                self.assertIn("url", spec_response.json()["data"])
                self.assertNotIn("values", spec_response.json()["data"])
                # No live HTTP server is running: recursive site requests would fail.
                response = self.client.get(reverse(png_name))
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response["Content-Type"], "image/png")
                with Image.open(BytesIO(response.content)) as image:
                    image.verify()

    def test_signup_is_disabled_without_creating_an_account_or_session(self):
        before = User.objects.count()
        response = self.client.post(reverse("account"), {
            "mode": "signup", "username": "new-student",
            "email": "new-student@illinois.edu", "password1": "example-password",
            "password2": "example-password",
        })
        self.assertRedirects(response, reverse("home"))
        self.assertEqual(User.objects.count(), before)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_png_reflects_changes_to_the_api_data_instead_of_an_empty_chart(self):
        url = reverse("vega-earned-spent-png")
        before = self.client.get(url)
        self.assertEqual(before.status_code, 200)
        Transaction.objects.filter(buyer=self.demo).update(agreed_price=400)
        after = self.client.get(url)
        self.assertEqual(after.status_code, 200)
        self.assertNotEqual(sha256(before.content).hexdigest(),
                            sha256(after.content).hexdigest())

    def test_all_pngs_render_when_wsgi_executable_is_not_python(self):
        with patch("marketplace.charts.sys.executable", "/usr/local/bin/uwsgi"):
            for name in (
                "vega-earned-spent-png",
                "vega-earned-spent-timeline-png",
                "vega-listing-inquiries-png",
            ):
                with self.subTest(endpoint=name):
                    response = self.client.get(reverse(name))
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response["Content-Type"], "image/png")
                    with Image.open(BytesIO(response.content)) as image:
                        image.verify()

    def test_a4_does_not_open_other_users_private_routes(self):
        self.assertEqual(self.client.get(reverse("seller-settings")).status_code, 403)
        self.client.force_login(User.objects.get(username="other"))
        self.assertEqual(self.client.post(reverse("listing_image_upload")).status_code, 403)
        response = self.client.get(reverse("profile-earned-spent-data"), {"user_id": "999"})
        self.assertEqual(response.json()[0]["amount"], 40.0)

    def test_a_real_account_cannot_be_used_as_the_public_demo_identity(self):
        User.objects.filter(pk=self.demo.pk).update(email="maya@illinois.edu")
        response = self.client.get(reverse("profile-earned-spent-data"))
        self.assertEqual(response.status_code, 404)
        self.assertIn("error", response.json())


@override_settings(A4_ASSIGNMENT_MODE=True, A4_DEMO_USERNAME="maya")
@tag("a4")
class A4SeedTests(TestCase):
    def test_seed_refuses_to_modify_a_database_with_non_demo_accounts(self):
        user = User.objects.create_user(username="existing", email="existing@illinois.edu")
        with self.assertRaises(CommandError):
            call_command("seed_a4_data", stdout=StringIO())
        user.refresh_from_db()
        self.assertEqual(user.email, "existing@illinois.edu")
        self.assertEqual(User.objects.count(), 1)
        self.assertEqual(Listing.objects.count(), 0)

    def test_seed_is_repeatable_and_contains_only_nonlogin_demo_identities(self):
        call_command("seed_a4_data", stdout=StringIO())
        counts = (User.objects.count(), Listing.objects.count(), Transaction.objects.count())
        self.assertGreaterEqual(counts[1], 8)
        self.assertGreaterEqual(counts[2], 4)
        self.assertTrue(all(user.email.endswith("@example.invalid") and
                            not user.has_usable_password() and
                            not user.is_staff and not user.is_superuser and
                            not user.email_verified and not user.google_subject
                            for user in User.objects.all()))
        self.assertEqual(EmailVerification.objects.count(), 0)
        call_command("seed_a4_data", stdout=StringIO())
        self.assertEqual(counts, (User.objects.count(), Listing.objects.count(),
                                  Transaction.objects.count()))
        self.assertEqual(self.client.get(reverse("profile-earned-spent-data")).json(), [
            {"activity": "Total Spent", "amount": 113.0},
            {"activity": "Total Earned", "amount": 18.0},
        ])
