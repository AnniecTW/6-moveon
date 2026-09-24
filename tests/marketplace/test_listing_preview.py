from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from marketplace.models import ItemCategory, ItemType, Listing, ListingImage, User


class ListingPreviewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.seller = User.objects.create_user(
            username="seller",
            email="seller@illinois.edu",
            password="test-password",
            display_name="Seller",
            email_verified=True,
            email_verified_at=timezone.now(),
        )
        cls.other_user = User.objects.create_user(
            username="other",
            email="other@illinois.edu",
            password="test-password",
            display_name="Other",
            email_verified=True,
            email_verified_at=timezone.now(),
        )
        category = ItemCategory.objects.create(category_name="Furniture")
        cls.item_type = ItemType.objects.create(
            category=category,
            item_type_name="Desk",
        )

    def create_draft(self, **overrides):
        data = {
            "seller": self.seller,
            "item_type": self.item_type,
            "title": "Oak desk",
            "listing_price": 50,
            "condition": Listing.Condition.GOOD,
            "fulfillment_option": Listing.Fulfillment.PICKUP,
            "status": Listing.Status.DRAFT,
        }
        data.update(overrides)
        return Listing.objects.create(**data)

    def create_form_data(self, action):
        return {
            "action": action,
            "title": "Oak desk",
            "listing_price": "50.00",
            "condition": Listing.Condition.GOOD,
            "item_type": str(self.item_type.pk),
            "fulfillment_pickup": "on",
            "image_ids": "",
        }

    def test_preview_action_saves_draft_and_redirects_to_preview(self):
        self.client.force_login(self.seller)

        response = self.client.post(
            reverse("listing-create-url"),
            self.create_form_data("preview"),
        )

        listing = Listing.objects.get(title="Oak desk")
        preview_url = reverse(
            "listing-preview-url",
            kwargs={"primary_key": listing.pk},
        )
        self.assertRedirects(response, preview_url)
        self.assertEqual(listing.status, Listing.Status.DRAFT)

        preview = self.client.get(preview_url)
        self.assertContains(preview, "This is a preview, not published yet.")
        self.assertContains(preview, "Back to edit")
        self.assertContains(preview, "Publish")

    def test_save_draft_action_redirects_home(self):
        self.client.force_login(self.seller)

        response = self.client.post(
            reverse("listing-create-url"),
            self.create_form_data("draft"),
        )

        self.assertRedirects(response, reverse("home"))

    def test_other_users_receive_404_for_draft_preview(self):
        listing = self.create_draft()
        self.client.force_login(self.other_user)

        response = self.client.get(
            reverse("listing-preview-url", kwargs={"primary_key": listing.pk})
        )

        self.assertEqual(response.status_code, 404)

    def test_publish_activates_draft_and_redirects_to_public_detail(self):
        listing = self.create_draft()
        self.client.force_login(self.seller)

        response = self.client.post(
            reverse("listing-publish-url", kwargs={"primary_key": listing.pk})
        )

        listing.refresh_from_db()
        self.assertEqual(listing.status, Listing.Status.ACTIVE)
        self.assertRedirects(
            response,
            reverse("listing-detail-url", kwargs={"primary_key": listing.pk}),
        )

    def test_get_publish_returns_method_not_allowed(self):
        listing = self.create_draft()
        self.client.force_login(self.seller)

        response = self.client.get(
            reverse("listing-publish-url", kwargs={"primary_key": listing.pk})
        )

        self.assertEqual(response.status_code, 405)

    def test_another_user_cannot_publish_a_draft(self):
        listing = self.create_draft()
        self.client.force_login(self.other_user)

        response = self.client.post(
            reverse("listing-publish-url", kwargs={"primary_key": listing.pk})
        )

        self.assertEqual(response.status_code, 404)
        listing.refresh_from_db()
        self.assertEqual(listing.status, Listing.Status.DRAFT)

    def test_publish_revalidates_saved_listing_before_activation(self):
        listing = self.create_draft()
        Listing.objects.filter(pk=listing.pk).update(title="")
        self.client.force_login(self.seller)

        response = self.client.post(
            reverse("listing-publish-url", kwargs={"primary_key": listing.pk})
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "This field is required.")
        listing.refresh_from_db()
        self.assertEqual(listing.status, Listing.Status.DRAFT)

    def test_edit_form_preloads_existing_photos(self):
        listing = self.create_draft()
        image = ListingImage.objects.create(
            listing=listing,
            uploaded_by=self.seller,
            external_url="https://images.example.invalid/desk.jpg",
            position=0,
        )
        self.client.force_login(self.seller)

        response = self.client.get(
            reverse("listing-update-url", kwargs={"primary_key": listing.pk})
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.context["initial_photos"],
            [{"id": image.pk, "url": image.url}],
        )
