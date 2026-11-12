import json
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase
from google.api_core.exceptions import ServiceUnavailable
from PIL import Image
from requests.exceptions import ReadTimeout

from marketplace.image_analysis import (
    GEMINI_FALLBACK_MODEL_NAME,
    GEMINI_MODEL_NAME,
    analyze_listing_images,
)


class PhotoAnalysisRecoveryTests(SimpleTestCase):
    def analyze(self):
        image = BytesIO()
        Image.new("RGB", (16, 16), "white").save(image, format="PNG")
        upload = SimpleUploadedFile("chair.png", image.getvalue())
        item_type = SimpleNamespace(
            pk=7, item_type_name="Chair",
            category=SimpleNamespace(category_name="Furniture"),
        )
        return analyze_listing_images([SimpleNamespace(image=upload)], [item_type], "test-key")

    @patch("marketplace.image_analysis.sleep")
    @patch("google.generativeai.configure")
    @patch("google.generativeai.GenerativeModel")
    def test_overload_and_timeout_recover_with_second_model(self, factory, configure, sleep):
        payload = {"recognizable": True, "title": "Chair", "description": "Wooden chair",
                   "item_type_id": 7, "condition": "GOOD"}
        for failure in (ServiceUnavailable("high demand"), ReadTimeout("timeout"), ValueError("truncated JSON")):
            with self.subTest(failure=type(failure).__name__):
                factory.reset_mock()
                primary, fallback = Mock(), Mock()
                primary.generate_content.side_effect = failure
                fallback.generate_content.return_value.text = json.dumps(payload)
                factory.side_effect = [primary, fallback]
                result, error = self.analyze()
                self.assertIsNone(error)
                self.assertEqual(result["title"], "Chair")
                self.assertEqual([call.args[0] for call in factory.call_args_list],
                                 [GEMINI_MODEL_NAME, GEMINI_FALLBACK_MODEL_NAME])
                configure.assert_called_with(api_key="test-key", transport="rest")

    @patch("marketplace.image_analysis.sleep")
    @patch("google.generativeai.configure")
    @patch("google.generativeai.GenerativeModel")
    def test_both_models_unavailable_returns_manual_entry_error(self, factory, configure, sleep):
        factory.return_value.generate_content.side_effect = ServiceUnavailable("high demand")
        with self.assertLogs("marketplace.image_analysis", level="WARNING"):
            result, error = self.analyze()
        self.assertIsNone(result)
        self.assertEqual(error["kind"], "service")
        self.assertEqual(factory.return_value.generate_content.call_count, 2)
