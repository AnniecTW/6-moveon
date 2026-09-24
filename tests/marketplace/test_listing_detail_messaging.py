from html import unescape
from urllib.parse import parse_qs, urlsplit

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from marketplace.models import ItemCategory, ItemType, Listing, User


class ListingDetailMessagingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.seller = User.objects.create_user(
            username="alex",
            email="alex@illinois.edu",
            password="test-password",
            display_name="Alex",
            email_verified=True,
            email_verified_at=timezone.now(),
        )
        cls.buyer = User.objects.create_user(
            username="maya",
            email="maya@illinois.edu",
            password="test-password",
            display_name="Maya",
            email_verified=True,
            email_verified_at=timezone.now(),
        )
        category = ItemCategory.objects.create(category_name="Furniture")
        item_type = ItemType.objects.create(category=category, item_type_name="Desk")
        cls.listing = Listing.objects.create(
            seller=cls.seller,
            item_type=item_type,
            title="Oak desk",
            listing_price=50,
            condition=Listing.Condition.GOOD,
            fulfillment_option=Listing.Fulfillment.PICKUP,
            status=Listing.Status.ACTIVE,
        )
        cls.detail_url = reverse(
            "listing-detail-url", kwargs={"primary_key": cls.listing.pk}
        )
        cls.messages_url = f"{reverse('messages')}?listing={cls.listing.pk}"

    def test_verified_non_seller_sees_message_seller_link(self):
        self.client.force_login(self.buyer)

        response = self.client.get(self.detail_url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            f'href="{self.messages_url}">Message Seller</a>',
        )

    def test_seller_does_not_see_message_seller_link(self):
        self.client.force_login(self.seller)

        response = self.client.get(self.detail_url)

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Message Seller")

    def test_guest_return_destination_survives_account_mode_switch(self):
        detail = self.client.get(self.detail_url)
        self.assertEqual(detail.status_code, 200)
        self.assertContains(
            detail,
            f'href="{self.messages_url}">Message Seller</a>',
        )

        account_redirect = self.client.get(self.messages_url)
        self.assertEqual(account_redirect.status_code, 302)
        account = self.client.get(account_redirect["Location"])

        self.assertEqual(account.status_code, 200)
        self.assertEqual(account.context["account_next"], self.messages_url)
        self.assertContains(account, f'name="next" value="{self.messages_url}"')
        signup_link = next(
            unescape(href)
            for href in account.content.decode().split('href="')
            if href.startswith(reverse("account") + "?mode=signup")
        ).split('"', 1)[0]
        self.assertEqual(
            parse_qs(urlsplit(signup_link).query)["next"], [self.messages_url]
        )

        login = self.client.post(
            reverse("account"),
            {
                "mode": "login",
                "username": self.buyer.username,
                "password": "test-password",
                "next": account.context["account_next"],
            },
        )
        self.assertEqual(login.status_code, 302)
        self.assertEqual(login["Location"], self.messages_url)
