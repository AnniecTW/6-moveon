"""Gemini-backed suggestions for seller listing forms."""

import json
import logging
from random import uniform
from time import sleep

from PIL import Image, UnidentifiedImageError
from google.api_core.exceptions import DeadlineExceeded, ServiceUnavailable
from requests.exceptions import Timeout

from .models import Listing

logger = logging.getLogger(__name__)

GEMINI_MODEL_NAME = "gemini-3.5-flash-lite"
GEMINI_FALLBACK_MODEL_NAME = "gemini-3.6-flash"
GEMINI_TIMEOUT_SECONDS = 45
MAX_IMAGE_DIMENSION = 1024


def analyze_listing_images(images, item_types, api_key):
    if not api_key:
        return None, {
            "kind": "service",
            "error": "Photo analysis is not configured. Please enter the listing details manually.",
        }

    try:
        visual_inputs = []
        for listing_image in images:
            try:
                with listing_image.image.open("rb") as source:
                    with Image.open(source) as image:
                        image.load()
                        image.thumbnail(
                            (MAX_IMAGE_DIMENSION, MAX_IMAGE_DIMENSION),
                            Image.Resampling.LANCZOS,
                        )
                        visual_inputs.append(image.convert("RGB"))
            except (Image.DecompressionBombError, OSError, UnidentifiedImageError, ValueError):
                return None, {
                    "kind": "photo",
                    "error": "A photo could not be read. Please upload a clear JPG, PNG, or WEBP image.",
                }

        if not visual_inputs:
            return None, {
                "kind": "photo",
                "error": "No photos are available to analyze. Upload an image or enter the details manually.",
            }

        available_types = [
            {
                "id": item_type.pk,
                "category": item_type.category.category_name,
                "name": item_type.item_type_name,
            }
            for item_type in item_types
        ]
        condition_values = [value for value, _label in Listing.Condition.choices]
        prompt = (
            "Analyze these photos for a secondhand campus marketplace listing. "
            "Write a warm, vivid, buyer-friendly description that highlights "
            "visible design details and practical appeal without sounding like an ad. "
            "Keep every claim grounded in the photos. Only describe details visible "
            "in the photos. Do not invent a brand, model, dimensions, defects, or "
            "working condition. If the product "
            "cannot be clearly identified, set recognizable to false. Choose an "
            "item_type_id only from the supplied list, otherwise use null. Choose "
            "condition only if the visible appearance supports it, otherwise null. "
            "Do not estimate a price. Return only JSON with keys recognizable "
            "(boolean), title (string), description (string), item_type_id "
            "(integer or null), and condition (allowed string or null). Keep the "
            "title under 80 characters and description under 1000 characters.\n\n"
            f"Available item types: {json.dumps(available_types)}\n"
            f"Allowed condition values: {json.dumps(condition_values)}"
        )

        import google.generativeai as genai

        # HTTPS works on networks that block or stall the SDK's default gRPC.
        genai.configure(api_key=api_key, transport="rest")
        response = None
        for attempt, model_name in enumerate((GEMINI_MODEL_NAME, GEMINI_FALLBACK_MODEL_NAME)):
            try:
                model = genai.GenerativeModel(model_name)
                response = model.generate_content(
                    [prompt, *visual_inputs],
                    generation_config=genai.GenerationConfig(
                        response_mime_type="application/json",
                        response_schema={
                            "type": "OBJECT",
                            "properties": {
                                "recognizable": {"type": "BOOLEAN"},
                                "title": {"type": "STRING"},
                                "description": {"type": "STRING"},
                                "item_type_id": {"type": "INTEGER", "nullable": True},
                                "condition": {
                                    "type": "STRING", "enum": condition_values,
                                    "nullable": True,
                                },
                            },
                            "required": ["recognizable", "title", "description", "item_type_id", "condition"],
                        },
                        max_output_tokens=2048,
                    ),
                    request_options={"timeout": GEMINI_TIMEOUT_SECONDS, "retry": None},
                )
                result = json.loads(response.text)
                break
            except (ServiceUnavailable, DeadlineExceeded, Timeout, ValueError):
                if attempt:
                    raise
                logger.warning("Photo model %s unavailable; trying %s.", model_name, GEMINI_FALLBACK_MODEL_NAME)
                sleep(uniform(0.4, 0.8))
        if not isinstance(result, dict) or result.get("recognizable") is not True:
            return None, {
                "kind": "photo",
                "error": "The item is not clear enough to identify. Try a brighter, sharper photo or enter the details manually.",
            }

        allowed_type_ids = {item_type.pk for item_type in item_types}
        title = result.get("title")
        description = result.get("description")
        item_type_id = result.get("item_type_id")
        condition = result.get("condition")
        if not isinstance(title, str):
            title = ""
        if not isinstance(description, str):
            description = ""
        title = title.strip()[:80]
        description = description.strip()[:1000]
        if isinstance(item_type_id, bool) or not isinstance(item_type_id, int) or item_type_id not in allowed_type_ids:
            item_type_id = None
        if condition not in condition_values:
            condition = None
        if not any((title, description, item_type_id, condition)):
            return None, {
                "kind": "photo",
                "error": "The photos did not produce usable suggestions. Try a clearer image or enter the details manually.",
            }

        return {
            "title": title,
            "description": description,
            "item_type_id": item_type_id,
            "condition": condition,
        }, None
    except Exception:
        logger.exception("Gemini listing image analysis failed.")
        return None, {
            "kind": "service",
            "error": "Photo analysis is temporarily unavailable. Please try again later or enter the listing details manually.",
        }
