import shutil
from io import BytesIO
from pathlib import Path
from tempfile import mkdtemp

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from PIL import Image

from .forms import ListingCreateForm
from .models import ItemCategory, ItemType, Listing, ListingImage


class ListingImageTestMixin:
    def setUp(self):
        self.media_root = Path(mkdtemp(prefix="moveon-listing-images-"))
        self.media_override = override_settings(MEDIA_ROOT=self.media_root)
        self.media_override.enable()
        self.addCleanup(self.media_override.disable)
        self.addCleanup(shutil.rmtree, self.media_root, ignore_errors=True)

        self.user = get_user_model().objects.create_user(
            username="seller",
            email="seller@example.invalid",
            display_name="Seller",
        )
        self.other_user = get_user_model().objects.create_user(
            username="other",
            email="other@example.invalid",
            display_name="Other",
        )
        category = ItemCategory.objects.create(category_name="Furniture")
        self.item_type = ItemType.objects.create(category=category, item_type_name="Desk")

    def image_file(self, image_format="PNG", filename=None):
        output = BytesIO()
        Image.new("RGB", (16, 16), "#718e70").save(output, format=image_format)
        extension = "jpg" if image_format == "JPEG" else image_format.lower()
        return SimpleUploadedFile(
            filename or f"photo.{extension}",
            output.getvalue(),
            content_type=f"image/{'jpeg' if image_format == 'JPEG' else extension}",
        )

    def listing_data(self, **overrides):
        data = {
            "title": "Desk",
            "listing_price": "50.00",
            "condition": "GOOD",
            "item_type": str(self.item_type.pk),
            "fulfillment_pickup": "on",
            "image_ids": "",
        }
        data.update(overrides)
        return data

    def external_image(self, user=None, listing=None, position=0, suffix=""):
        return ListingImage.objects.create(
            uploaded_by=user or self.user,
            listing=listing,
            external_url=f"https://cdn.example.invalid/photo{suffix or position}.jpg",
            position=position,
        )


class ListingImageUploadTests(ListingImageTestMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.user)
        self.url = reverse("listing_image_upload")

    def test_valid_file_is_saved(self):
        response = self.client.post(self.url, {"file": self.image_file()})

        self.assertEqual(response.status_code, 201)
        image = ListingImage.objects.get()
        self.assertEqual(response.json(), {"id": image.pk, "url": image.url})
        self.assertTrue(image.image.name.startswith("listing_images/"))

    def test_deleting_uploaded_image_removes_stored_file(self):
        self.client.post(self.url, {"file": self.image_file()})
        image = ListingImage.objects.get()
        stored_path = Path(image.image.path)
        self.assertTrue(stored_path.exists())

        image.delete()

        self.assertFalse(stored_path.exists())

    def test_wrong_type_is_rejected(self):
        response = self.client.post(
            self.url,
            {"file": SimpleUploadedFile("notes.txt", b"not an image", content_type="text/plain")},
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("valid image", response.json()["error"])

    def test_oversize_file_is_rejected(self):
        response = self.client.post(
            self.url,
            {"file": SimpleUploadedFile("large.jpg", b"x" * (5 * 1024 * 1024 + 1))},
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("5MB", response.json()["error"])

    def test_fake_extension_with_non_image_content_is_rejected(self):
        response = self.client.post(
            self.url,
            {"file": SimpleUploadedFile("fake.jpg", b"plain text")},
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("valid image", response.json()["error"])

    def test_valid_external_url_is_saved_without_fetching(self):
        external_url = "https://images.example.invalid/item.webp"
        response = self.client.post(self.url, {"url": external_url})

        self.assertEqual(response.status_code, 201)
        image = ListingImage.objects.get()
        self.assertEqual(image.external_url, external_url)
        self.assertEqual(image.url, external_url)

    def test_invalid_external_url_is_rejected(self):
        response = self.client.post(self.url, {"url": "ftp://example.invalid/item.jpg"})

        self.assertEqual(response.status_code, 400)
        self.assertIn("HTTP or HTTPS", response.json()["error"])

    def test_unauthenticated_upload_is_rejected(self):
        self.client.logout()

        response = self.client.post(self.url, {"url": "https://example.invalid/item.jpg"})

        self.assertEqual(response.status_code, 302)


class ListingImageFormTests(ListingImageTestMixin, TestCase):
    def test_another_users_image_ids_are_rejected(self):
        image = self.external_image(user=self.other_user)
        form = ListingCreateForm(
            data=self.listing_data(image_ids=str(image.pk)),
            user=self.user,
        )

        self.assertFalse(form.is_valid())
        self.assertIn("uploaded", str(form.errors["image_ids"]))

    def test_create_attaches_images_in_submitted_order_and_sets_cover(self):
        images = [self.external_image(suffix=str(index)) for index in range(3)]
        form = ListingCreateForm(
            data=self.listing_data(image_ids=",".join(str(image.pk) for image in images)),
            user=self.user,
        )
        form.instance.seller = self.user
        form.instance.status = Listing.Status.DRAFT

        self.assertTrue(form.is_valid(), form.errors)
        listing = form.save()

        ordered = list(listing.images.all())
        self.assertEqual([image.pk for image in ordered], [image.pk for image in images])
        self.assertEqual([image.position for image in ordered], [0, 1, 2])
        self.assertEqual(listing.cover_image_url, images[0].url)

    def test_edit_reorders_and_removes_images(self):
        listing = Listing.objects.create(
            seller=self.user,
            item_type=self.item_type,
            title="Desk",
            listing_price=50,
            condition=Listing.Condition.GOOD,
            fulfillment_option=Listing.Fulfillment.PICKUP,
            status=Listing.Status.DRAFT,
        )
        images = [self.external_image(listing=listing, suffix=str(index)) for index in range(3)]
        form = ListingCreateForm(
            instance=listing,
            data=self.listing_data(image_ids=f"{images[2].pk},{images[0].pk}"),
            user=self.user,
        )

        self.assertTrue(form.is_valid(), form.errors)
        form.save()

        self.assertEqual(
            list(listing.images.values_list("pk", "position")),
            [(images[2].pk, 0), (images[0].pk, 1)],
        )
        self.assertFalse(ListingImage.objects.filter(pk=images[1].pk).exists())

    def test_more_than_maximum_images_is_rejected(self):
        images = [self.external_image(suffix=str(index)) for index in range(Listing.MAX_IMAGES + 1)]
        form = ListingCreateForm(
            data=self.listing_data(image_ids=",".join(str(image.pk) for image in images)),
            user=self.user,
        )

        self.assertFalse(form.is_valid())
        self.assertIn("at most", str(form.errors["image_ids"]))


class LegacyListingImageMigrationTests(TransactionTestCase):
    reset_sequences = True

    def restore_latest_migrations(self):
        from django.db.migrations.executor import MigrationExecutor

        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())

    def test_legacy_image_url_is_copied(self):
        from django.db.migrations.executor import MigrationExecutor

        migrate_from = [("marketplace", "0009_merge_20260923_2240")]
        migrate_to = [("marketplace", "0010_listingimage")]
        executor = MigrationExecutor(connection)
        self.addCleanup(self.restore_latest_migrations)
        executor.migrate(migrate_from)
        old_apps = executor.loader.project_state(migrate_from).apps
        User = old_apps.get_model("marketplace", "User")
        ItemCategory = old_apps.get_model("marketplace", "ItemCategory")
        ItemType = old_apps.get_model("marketplace", "ItemType")
        Listing = old_apps.get_model("marketplace", "Listing")
        user = User.objects.create(
            username="migration-seller",
            email="migration@example.invalid",
            display_name="Migration Seller",
        )
        category = ItemCategory.objects.create(category_name="Migration Furniture")
        item_type = ItemType.objects.create(category=category, item_type_name="Table")
        listing = Listing.objects.create(
            seller=user,
            item_type=item_type,
            title="Legacy Table",
            image_url="https://example.invalid/legacy.jpg",
            listing_price=25,
            condition="GOOD",
            fulfillment_option="PICKUP",
            status="DRAFT",
        )

        # Rebuild the executor after rolling back so its migration graph and
        # recorder state reflect the schema that is about to be applied.
        executor = MigrationExecutor(connection)
        executor.migrate(migrate_to)
        new_apps = executor.loader.project_state(migrate_to).apps
        ListingImage = new_apps.get_model("marketplace", "ListingImage")
        copied = ListingImage.objects.get(listing_id=listing.pk)
        self.assertEqual(copied.external_url, listing.image_url)
        self.assertEqual(copied.uploaded_by_id, user.pk)
        self.assertEqual(copied.position, 0)
